package com.dianping.swallow.consumerserver.buffer;

import java.util.List;
import java.util.Set;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.locks.ReentrantLock;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import com.dianping.swallow.common.message.Message;

public class MessageBlockingQueue extends LinkedBlockingQueue<Message> {

   private static final long   serialVersionUID  = -633276713494338593L;
   private static final Logger LOG               = LoggerFactory.getLogger(MessageBlockingQueue.class);
   private static final int    DEFAULT_THRESHOLD = 50;

   private final String        cid;
   private final String        topicId;

   /** 最小剩余数量,当queue的消息数量小于threshold时，会触发从数据库加载数据的操作 */
   private final int           threshold;

   protected MessageRetriever  messageRetriever;

   private ReentrantLock       reentrantLock     = new ReentrantLock();

   protected volatile Long     tailMessageId;
   protected Set<String>       messageTypeSet;
   private volatile Thread     messageRetrieverDemonThread;

   public MessageBlockingQueue(String cid, String topicId, int threshold, int capacity, Long messageIdOfTailMessage) {
      super(capacity);
      //能运行到这里，说明capacity>0
      this.cid = cid;
      this.topicId = topicId;
      if (threshold < 0)
         throw new IllegalArgumentException("threshold: " + threshold);
      this.threshold = threshold;
      if (messageIdOfTailMessage == null)
         throw new IllegalArgumentException("messageIdOfTailMessage is null.");
      this.tailMessageId = messageIdOfTailMessage;
   }

   public MessageBlockingQueue(String cid, String topicId, int threshold, Long messageIdOfTailMessage) {
      this.cid = cid;
      this.topicId = topicId;
      if (threshold < 0)
         throw new IllegalArgumentException("threshold: " + threshold);
      this.threshold = threshold;
      if (messageIdOfTailMessage == null)
         throw new IllegalArgumentException("messageIdOfTailMessage is null.");
      this.tailMessageId = messageIdOfTailMessage;
   }

   public MessageBlockingQueue(String cid, String topicId, Long messageIdOfTailMessage) {
      this.cid = cid;
      this.topicId = topicId;
      this.threshold = DEFAULT_THRESHOLD;
      if (messageIdOfTailMessage == null)
         throw new IllegalArgumentException("messageIdOfTailMessage is null.");
      this.tailMessageId = messageIdOfTailMessage;
   }

   public MessageBlockingQueue(String cid, String topicId, int threshold, int capacity, Long messageIdOfTailMessage,
                               Set<String> messageTypeSet) {
      super(capacity);
      //能运行到这里，说明capacity>0
      this.cid = cid;
      this.topicId = topicId;
      if (threshold < 0)
         throw new IllegalArgumentException("threshold: " + threshold);
      this.threshold = threshold;
      if (messageIdOfTailMessage == null)
         throw new IllegalArgumentException("messageIdOfTailMessage is null.");
      this.tailMessageId = messageIdOfTailMessage;
      this.messageTypeSet = messageTypeSet;
   }

   public MessageBlockingQueue(String cid, String topicId, int threshold, Long tailMessageId, Set<String> messageTypeSet) {
      this.cid = cid;
      this.topicId = topicId;
      if (threshold < 0)
         throw new IllegalArgumentException("threshold: " + threshold);
      this.threshold = threshold;
      if (tailMessageId == null)
         throw new IllegalArgumentException("messageIdOfTailMessage is null.");
      this.tailMessageId = tailMessageId;
      this.messageTypeSet = messageTypeSet;
   }

   public MessageBlockingQueue(String cid, String topicId, Long messageIdOfTailMessage, Set<String> messageTypeSet) {
      this.cid = cid;
      this.topicId = topicId;
      this.threshold = DEFAULT_THRESHOLD;
      if (messageIdOfTailMessage == null)
         throw new IllegalArgumentException("messageIdOfTailMessage is null.");
      this.tailMessageId = messageIdOfTailMessage;
      this.messageTypeSet = messageTypeSet;
   }

   public Message poll() {
      //如果剩余元素数量小于最低限制值threshold，就启动一个“获取DB数据的后台线程”去DB获取数据，并添加到Queue的尾部
      if (super.size() < threshold) {
         ensureLeftMessage();
      }
      return super.poll();
   }

   public Message poll(long timeout, TimeUnit unit) throws InterruptedException {
      //如果剩余元素数量小于最低限制值threshold，就启动一个“获取DB数据的后台线程”去DB获取数据，并添加到Queue的尾部
      if (super.size() < threshold) {
         ensureLeftMessage();
      }
      return super.poll(timeout, unit);
   }

   /**
    * 启动一个“获取DB数据的后台线程”去DB获取数据，并添加到Queue的尾部
    */
   private void ensureLeftMessage() {
      if (messageRetriever == null) {
         return;
      }
      if (reentrantLock.tryLock()) {//只有一个线程能启动“获取DB数据的后台线程”
         try {
            if (messageRetrieverDemonThread == null || !messageRetrieverDemonThread.isAlive()) {//而且后台线程已经在运行，则不能再启动
               messageRetrieverDemonThread = new Thread(new Runnable() {
                  @Override
                  public void run() {
                     try {
                        List<Message> messages = messageRetriever.retriveMessage(MessageBlockingQueue.this.topicId,
                              MessageBlockingQueue.this.tailMessageId, MessageBlockingQueue.this.messageTypeSet);
                        if (messages != null) {
                           int size = messages.size();
                           for (int i = 0; i < size; i++) {
                              Message message = messages.get(i);
                              try {
                                 MessageBlockingQueue.this.put(message);
                                 Long messageId = message.getMessageId();
                                 if (messageId == null) {
                                    throw new IllegalStateException("the retrived message's messageId is null:"
                                          + message);
                                 }
                                 tailMessageId = messageId;
                                 if (LOG.isDebugEnabled()) {
                                    LOG.debug("add message to (topic=" + topicId + ",cid=" + cid + ") queue:"
                                          + message.toString());
                                 }
                              } catch (InterruptedException e) {
                                 LOG.error(e.getMessage(), e);
                                 break;
                              }
                           }
                        }
                     } catch (Exception e1) {
                        LOG.error(e1.getMessage(), e1);
                     } finally {
                        LOG.info("thread done:" + Thread.currentThread().getName());
                     }
                  }
               });
               messageRetrieverDemonThread
                     .setName("MessageRetriever-(topic=" + this.topicId + ",cid=" + this.cid + ")");
               messageRetrieverDemonThread.setDaemon(true);
               messageRetrieverDemonThread.start();
               LOG.info("thread start:" + messageRetrieverDemonThread.getName());
            }
         } finally {
            reentrantLock.unlock();
         }
      }
   }

   public MessageRetriever getMessageRetriever() {
      return messageRetriever;
   }

   public void setMessageRetriever(MessageRetriever messageRetriever) {
      this.messageRetriever = messageRetriever;
   }

}
