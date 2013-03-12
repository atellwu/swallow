package com.dianping.swallow.example.producer;

import com.dianping.swallow.common.message.Destination;
import com.dianping.swallow.producer.Producer;
import com.dianping.swallow.producer.ProducerConfig;
import com.dianping.swallow.producer.impl.ProducerFactoryImpl;

public class AsyncProducerExample {

    public static void main(String[] args) throws Exception {
        ProducerConfig config = new ProducerConfig();
        //        config.setMode(ProducerMode.ASYNC_MODE);
        config.setFilequeueBaseDir("/data/appdatas/filequeue/abc");
        Producer p = ProducerFactoryImpl.getInstance().createProducer(Destination.topic("example"), config);
        for (int i = 0; i < 10; i++) {
            String msg = AsyncProducerExample.class.getSimpleName() + ": 消息-" + i;
            p.sendMessage(msg);
            System.out.println("Sended msg:" + msg);
            Thread.sleep(500);
        }
    }

}
