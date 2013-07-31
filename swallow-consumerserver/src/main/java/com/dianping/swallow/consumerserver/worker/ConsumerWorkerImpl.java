package com.dianping.swallow.consumerserver.worker;

import java.lang.ref.WeakReference;
import java.util.Map;
import java.util.Map.Entry;
import java.util.Queue;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

import org.jboss.netty.channel.Channel;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import com.dianping.cat.Cat;
import com.dianping.cat.CatConstants;
import com.dianping.cat.message.Transaction;
import com.dianping.hawk.jmx.HawkJMXUtil;
import com.dianping.swallow.common.consumer.ConsumerType;
import com.dianping.swallow.common.consumer.MessageFilter;
import com.dianping.swallow.common.internal.consumer.ACKHandlerType;
import com.dianping.swallow.common.internal.dao.AckDAO;
import com.dianping.swallow.common.internal.dao.MessageDAO;
import com.dianping.swallow.common.internal.message.SwallowMessage;
import com.dianping.swallow.common.internal.packet.PktMessage;
import com.dianping.swallow.common.internal.threadfactory.DefaultPullStrategy;
import com.dianping.swallow.common.internal.threadfactory.MQThreadFactory;
import com.dianping.swallow.common.internal.threadfactory.PullStrategy;
import com.dianping.swallow.common.internal.util.IPUtil;
import com.dianping.swallow.common.internal.util.MongoUtils;
import com.dianping.swallow.common.message.Message;
import com.dianping.swallow.consumerserver.buffer.CloseableBlockingQueue;
import com.dianping.swallow.consumerserver.buffer.SwallowBuffer;
import com.dianping.swallow.consumerserver.config.ConfigManager;

public final class ConsumerWorkerImpl implements ConsumerWorker {
    private static final Logger    LOG               = LoggerFactory.getLogger(ConsumerWorkerImpl.class);

    private ConsumerInfo           consumerInfo;
    private BlockingQueue<Channel> freeChannels      = new LinkedBlockingQueue<Channel>();
    private Map<Channel, String>   connectedChannels = new ConcurrentHashMap<Channel, String>();

    public Map<Channel, String> getConnectedChannels() {
        return connectedChannels;
    }

    private CloseableBlockingQueue<Message> messageQueue   = null;

    private AckDAO                          ackDao;
    private SwallowBuffer                   swallowBuffer;
    private MessageDAO                      messageDao;
    private Queue<PktMessage>               cachedMessages = new ConcurrentLinkedQueue<PktMessage>();

    public Queue<PktMessage> getCachedMessages() {
        return cachedMessages;
    }

    private MQThreadFactory                        threadFactory;
    private String                                 consumerid;
    private String                                 topicName;
    private volatile boolean                       getMessageisAlive = true;
    private volatile boolean                       started           = false;
    private ExecutorService                        ackExecutor;
    private PullStrategy                           pullStgy;

    private ConfigManager                          configManager;
    private Map<Channel, Map<PktMessage, Boolean>> waitAckMessages   = new ConcurrentHashMap<Channel, Map<PktMessage, Boolean>>();
    private volatile long                          maxAckedMessageId = 0L;

    public Map<Channel, Map<PktMessage, Boolean>> getWaitAckMessages() {
        return waitAckMessages;
    }

    private MessageFilter messageFilter;

    public ConsumerWorkerImpl(ConsumerInfo consumerInfo, ConsumerWorkerManager workerManager,
                              MessageFilter messageFilter) {
        this.consumerInfo = consumerInfo;
        this.configManager = workerManager.getConfigManager();
        this.ackDao = workerManager.getAckDAO();
        this.messageDao = workerManager.getMessageDAO();
        this.swallowBuffer = workerManager.getSwallowBuffer();
        this.threadFactory = workerManager.getThreadFactory();
        this.messageFilter = messageFilter;
        topicName = consumerInfo.getConsumerId().getDest().getName();
        consumerid = consumerInfo.getConsumerId().getConsumerId();
        pullStgy = new DefaultPullStrategy(configManager.getPullFailDelayBase(),
                configManager.getPullFailDelayUpperBound());

        // consumerInfo的type不允许AT_MOST模式，遇到则修改成AT_LEAST模式
        if (this.consumerInfo.getConsumerType() == ConsumerType.DURABLE_AT_MOST_ONCE) {
            this.consumerInfo = new ConsumerInfo(consumerInfo.getConsumerId(), ConsumerType.DURABLE_AT_LEAST_ONCE);
            LOG.info("ConsumerClient[topicName=" + topicName + ", consumerid=" + consumerid
                    + "] used ConsumerType.DURABLE_AT_MOST_ONCE. Now change it to ConsumerType.DURABLE_AT_LEAST_ONCE.");
        }

        ackExecutor = new ThreadPoolExecutor(1, 1, Long.MAX_VALUE, TimeUnit.DAYS, new LinkedBlockingQueue<Runnable>(),
                new MQThreadFactory("swallow-ack-"));

        startMessageFetcherThread();

        //Hawk监控
        String hawkMBeanName = topicName + '-' + consumerid + "-ConsumerWorkerImpl";
        HawkJMXUtil.unregisterMBean(hawkMBeanName);
        HawkJMXUtil.registerMBean(hawkMBeanName, new HawkMBean(this));
    }

    @Override
    public void handleAck(final Channel channel, final Long ackedMsgId, final ACKHandlerType type) {
        ackExecutor.execute(new Runnable() {
            @Override
            public void run() {
                try {
                    updateWaitAckMessages(channel, ackedMsgId);
                    updateMaxMessageId(ackedMsgId, channel);
                    if (ACKHandlerType.CLOSE_CHANNEL.equals(type)) {
                        LOG.info("receive ack(type=" + type + ") from " + channel.getRemoteAddress());
                        channel.close();
                        //                  handleChannelDisconnect(channel); //channel.close()会触发netty调用handleChannelDisconnect(channel);
                    } else if (ACKHandlerType.SEND_MESSAGE.equals(type)) {
                        freeChannels.add(channel);
                    }
                } catch (Exception e) {
                    LOG.error("handleAck wrong!", e);
                }
            }
        });

    }

    //只有AT_LEAST_ONCE模式的consumer需要更新等待ack的message列表，AT_MOST_ONCE没有等待ack的message列表
    private void updateWaitAckMessages(Channel channel, Long ackedMsgId) {
        if (ConsumerType.DURABLE_AT_LEAST_ONCE.equals(consumerInfo.getConsumerType())) {
            Map<PktMessage, Boolean> messages = waitAckMessages.get(channel);
            if (messages != null) {
                SwallowMessage swallowMsg = new SwallowMessage();
                swallowMsg.setMessageId(ackedMsgId);
                PktMessage mockPktMessage = new PktMessage(consumerInfo.getConsumerId().getDest(), swallowMsg);
                messages.remove(mockPktMessage);
            }

        }

    }

    private void updateMaxMessageId(Long ackedMsgId, Channel channel) {
        if (ackedMsgId != null && ConsumerType.DURABLE_AT_LEAST_ONCE.equals(consumerInfo.getConsumerType())) {
            //         ackDao.add(topicName, consumerid, ackedMsgId, connectedChannels.get(channel));
            LOG.info("Receive ACK(" + topicName + "," + consumerid + "," + ackedMsgId + ") from "
                    + connectedChannels.get(channel));
            maxAckedMessageId = Math.max(maxAckedMessageId, ackedMsgId);
        }
    }

    @Override
    public synchronized void handleChannelDisconnect(Channel channel) {
        connectedChannels.remove(channel);
        if (ConsumerType.DURABLE_AT_LEAST_ONCE.equals(consumerInfo.getConsumerType())) {
            Map<PktMessage, Boolean> messageMap = waitAckMessages.get(channel);
            if (messageMap != null) {
                try {
                    Thread.sleep(100);
                } catch (InterruptedException e) {
                    //netty自身的线程，不会有谁Interrupt。
                }
                for (Map.Entry<PktMessage, Boolean> messageEntry : messageMap.entrySet()) {
                    cachedMessages.add(messageEntry.getKey());
                }
                waitAckMessages.remove(channel);
            }
        }

    }

    private void startMessageFetcherThread() {

        threadFactory.newThread(new Runnable() {

            @Override
            public void run() {
                while (getMessageisAlive) {
                    sendMessageByPollFreeChannelQueue();
                }
                LOG.info("message fetcher thread closed");
            }
        }, consumerInfo.toString() + "-messageFetcher-").start();

    }

    @Override
    public void handleGreet(final Channel channel, final int clientThreadCount) {
        ackExecutor.execute(new Runnable() {
            @Override
            public void run() {

                connectedChannels.put(channel, IPUtil.getIpFromChannel(channel));
                started = true;
                for (int i = 0; i < clientThreadCount; i++) {
                    freeChannels.add(channel);
                }
            }
        });
    }

    @Override
    public void closeMessageFetcherThread() {
        getMessageisAlive = false;
    }

    @Override
    public void closeAckExecutor() {
        ackExecutor.shutdownNow();
    }

    @Override
    public void close() {
        getMessageisAlive = false;
        messageQueue.close();
        //取消监控
        String hawkMBeanName = topicName + '-' + consumerid + "-ConsumerWorkerImpl";
        HawkJMXUtil.unregisterMBean(hawkMBeanName);
    }

    public long getMessageIdOfTailMessage(String topicName, String consumerId, Channel channel) {
        Long maxMessageId = null;
        if (!ConsumerType.NON_DURABLE.equals(consumerInfo.getConsumerType())) {
            maxMessageId = ackDao.getMaxMessageId(topicName, consumerId);
        }
        if (maxMessageId == null) {
            maxMessageId = messageDao.getMaxMessageId(topicName);

            if (maxMessageId == null) {
                maxMessageId = MongoUtils.getLongByCurTime();
            }
            if (!ConsumerType.NON_DURABLE.equals(consumerInfo.getConsumerType())) {
                //consumer连接上后，以此时为时间基准，以后的消息都可以收到，因此需要插入ack。
                ackDao.add(topicName, consumerId, maxMessageId, connectedChannels.get(channel));
            }
        }
        return maxMessageId;
    }

    private void sendMessageByPollFreeChannelQueue() {
        try {
            while (getMessageisAlive) {
                Channel channel = freeChannels.take();
                //如果未连接，则不做处理
                if (channel.isConnected()) {
                    //创建消息缓冲QUEUE
                    if (messageQueue == null) {
                        try {
                            long messageIdOfTailMessage = getMessageIdOfTailMessage(topicName, consumerid, channel);
                            messageQueue = swallowBuffer.createMessageQueue(topicName, consumerid,
                                    messageIdOfTailMessage, messageFilter);
                        } catch (RuntimeException e) {
                            LOG.error("Error create message queue from SwallowBuffer!", e);
                            freeChannels.add(channel);
                            Thread.sleep(configManager.getRetryIntervalWhenMongoException());
                            continue;
                        }
                    }
                    if (cachedMessages.isEmpty()) {
                        putMsg2CachedMsgFromMsgQueue();
                    }
                    if (!cachedMessages.isEmpty()) {
                        sendMsgFromCachedMessages(channel);
                    }

                }

            }
        } catch (InterruptedException e) {
            LOG.info("get message from messageQueue thread InterruptedException", e);
        }
    }

    private void sendMsgFromCachedMessages(Channel channel) throws InterruptedException {
        PktMessage preparedMessage = cachedMessages.poll();
        Long messageId = preparedMessage.getContent().getMessageId();

        //Cat begin
        Transaction consumerServerTransaction = Cat.getProducer().newTransaction("Out:" + topicName,
                consumerid + ":" + IPUtil.getIpFromChannel(channel));
        String childEventId;
        try {
            childEventId = Cat.getProducer().createMessageId();
            preparedMessage.setCatEventID(childEventId);
            Cat.getProducer().logEvent(CatConstants.TYPE_REMOTE_CALL, "ConsumedByWhom",
                    com.dianping.cat.message.Message.SUCCESS, childEventId);
        } catch (Exception e) {
            childEventId = "UnknownMessageId";
        }
        //Cat end

        try {
            channel.write(preparedMessage);
            //如果是AT_MOST模式，收到ACK之前更新messageId的类型
            if (ConsumerType.DURABLE_AT_MOST_ONCE.equals(consumerInfo.getConsumerType())) {
                ackDao.add(topicName, consumerid, messageId, connectedChannels.get(channel));
            }
            //如果是AT_LEAST模式，发送完后，在server端记录已发送但未收到ACK的消息记录
            if (ConsumerType.DURABLE_AT_LEAST_ONCE.equals(consumerInfo.getConsumerType())) {
                Map<PktMessage, Boolean> messageMap = waitAckMessages.get(channel);
                if (channel.isConnected()) {
                    if (messageMap == null) {
                        messageMap = new ConcurrentHashMap<PktMessage, Boolean>();
                        waitAckMessages.put(channel, messageMap);
                    }
                    messageMap.put(preparedMessage, Boolean.TRUE);
                } else {
                    cachedMessages.add(preparedMessage);
                }
            }
            //Cat begin
            consumerServerTransaction.addData("mid", preparedMessage.getContent().getMessageId());
            consumerServerTransaction.setStatus(com.dianping.cat.message.Message.SUCCESS);
            //Cat end
        } catch (RuntimeException e) {
            LOG.error(consumerInfo.toString() + "：channel write error.", e);
            cachedMessages.add(preparedMessage);

            //Cat begin
            consumerServerTransaction.addData(preparedMessage.getContent().toKeyValuePairs());
            consumerServerTransaction.setStatus(e);
            Cat.getProducer().logError(e);
        } finally {
            consumerServerTransaction.complete();
        }
        //Cat end
    }

    private void putMsg2CachedMsgFromMsgQueue() throws InterruptedException {
        SwallowMessage message = null;
        while (getMessageisAlive) {
            //从blockQueue中获取消息
            message = (SwallowMessage) messageQueue.poll(pullStgy.fail(false), TimeUnit.MILLISECONDS);
            if (message != null) {
                pullStgy.succeess();
                break;
            }
        }
        //收到close命令后,可能没有取得消息,此时,message仍然可能为null
        if (message != null) {
            cachedMessages.add(new PktMessage(consumerInfo.getConsumerId().getDest(), message));
        }

    }

    @Override
    public boolean allChannelDisconnected() {
        return started && connectedChannels.isEmpty();
    }

    @Override
    public long getMaxAckedMessageId() {
        return maxAckedMessageId;
    }

    @Override
    public ConsumerType getConsumerType() {
        return consumerInfo.getConsumerType();
    }

    /**
     * 用于Hawk监控
     */
    public static class HawkMBean {

        private final WeakReference<ConsumerWorkerImpl> consumerWorkerImpl;

        private HawkMBean(ConsumerWorkerImpl consumerWorkerImpl) {
            this.consumerWorkerImpl = new WeakReference<ConsumerWorkerImpl>(consumerWorkerImpl);
        }

        public String getConnectedChannels() {
            if (consumerWorkerImpl.get() != null) {
                StringBuilder sb = new StringBuilder();
                if (consumerWorkerImpl.get().connectedChannels != null) {
                    for (Channel channel : consumerWorkerImpl.get().connectedChannels.keySet()) {
                        sb.append(channel.getRemoteAddress()).append("(isConnected:").append(channel.isConnected())
                                .append(')');
                    }
                }
                return sb.toString();
            }
            return null;
        }

        public String getFreeChannels() {
            if (consumerWorkerImpl.get() != null) {
                StringBuilder sb = new StringBuilder();
                if (consumerWorkerImpl.get().freeChannels != null) {
                    for (Channel channel : consumerWorkerImpl.get().freeChannels) {
                        sb.append(channel.getRemoteAddress()).append("(isConnected:").append(channel.isConnected())
                                .append(')');
                    }
                }
                return sb.toString();
            }
            return null;
        }

        public String getConsumerInfo() {
            if (consumerWorkerImpl.get() != null) {
                return "ConsumerId=" + consumerWorkerImpl.get().consumerInfo.getConsumerId() + ",ConsumerType="
                        + consumerWorkerImpl.get().consumerInfo.getConsumerType();
            }
            return null;

        }

        //      public String getConsumerid() {
        //         return consumerid;
        //      }

        public String getTopicName() {
            if (consumerWorkerImpl.get() != null) {
                return consumerWorkerImpl.get().topicName;
            }
            return null;
        }

        public String getCachedMessages() {
            if (consumerWorkerImpl.get() != null) {
                if (consumerWorkerImpl.get().cachedMessages != null) {
                    return consumerWorkerImpl.get().cachedMessages.toString();
                }
            }
            return null;
        }

        public String getWaitAckMessages() {
            if (consumerWorkerImpl.get() != null) {
                StringBuilder sb = new StringBuilder();
                if (consumerWorkerImpl.get().waitAckMessages != null) {
                    for (Entry<Channel, Map<PktMessage, Boolean>> waitAckMessage : consumerWorkerImpl.get().waitAckMessages
                            .entrySet()) {
                        if (waitAckMessage.getValue().size() != 0) {
                            sb.append(waitAckMessage.getKey().getRemoteAddress()).append(
                                    waitAckMessage.getValue().toString());
                        }
                    }
                }
                return sb.toString();
            }
            return null;

        }

        public Boolean isGetMessageisAlive() {
            if (consumerWorkerImpl.get() != null) {
                return consumerWorkerImpl.get().getMessageisAlive;
            }
            return null;
        }

        public Boolean isStarted() {
            if (consumerWorkerImpl.get() != null) {
                return consumerWorkerImpl.get().started;
            }
            return null;
        }

        public String getMaxAckedMessageId() {
            if (consumerWorkerImpl.get() != null) {
                return Long.toString(consumerWorkerImpl.get().maxAckedMessageId);
            }
            return null;

        }

        public String getMessageFilter() {
            if (consumerWorkerImpl.get() != null) {
                if (consumerWorkerImpl.get().messageFilter != null) {
                    return consumerWorkerImpl.get().messageFilter.toString();
                }
            }
            return null;
        }

    }

}
