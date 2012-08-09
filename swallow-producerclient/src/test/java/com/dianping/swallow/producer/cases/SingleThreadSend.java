package com.dianping.swallow.producer.cases;

import java.util.Map;

import com.dianping.cat.Cat;
import com.dianping.cat.message.internal.MessageId;
import com.dianping.cat.message.spi.MessageTree;
import com.dianping.swallow.common.message.Destination;
import com.dianping.swallow.producer.Producer;
import com.dianping.swallow.producer.ProducerConfig;
import com.dianping.swallow.producer.ProducerMode;
import com.dianping.swallow.producer.impl.ProducerFactoryImpl;

@SuppressWarnings("unused")
class DemoObject {
   private int        a  = 1000;
   private float      b  = 10.123f;
   private String     c  = "hello world";
   private TempObject to = new TempObject();

   public int getA() {
      return a;
   }

   public void setA(int a) {
      this.a = a;
   }
}

class TempObject {
   @SuppressWarnings("unused")
   private String d = "hello kitty";
}

public class SingleThreadSend {

   public static void syncSendSome(String content, int count, int freq, Map<String, String> properties, String type)
         throws Exception {
      ProducerConfig config = new ProducerConfig();
      config.setSyncRetryTimes(2);
      Producer producer = ProducerFactoryImpl.getInstance().createProducer(Destination.topic("example"), config);
      int sent = 0;
//      System.out.println(">>>>>>>>>sleep a while");
//      Thread.sleep(60000);
      System.out.println(">>>>>>>>>>send start.");
      long begin = System.currentTimeMillis();
      if (count <= 0) {
         while (true) {
            System.out.println(producer.sendMessage(++sent + ": " + content, properties, type));
            Thread.sleep(freq < 0 ? 0 : freq);
         }
      } else {
         for (int i = 0; i < count; i++) {
//            producer.sendMessage(++sent + ": " + content, properties, type);
            producer.sendMessage(content);
            //            System.out.println();
//            Thread.sleep(freq < 0 ? 0 : freq);
         }
      }
      System.out.println(">>>>>>>>>>>send end. cost: " + (System.currentTimeMillis() - begin));
   }

   public static void syncSendSomeObjectDemoWithZipped(int count, int freq) throws Exception {
      ProducerConfig config = new ProducerConfig();
      config.setAsyncRetryTimes(1);
      config.setZipped(true);

      Producer producer = ProducerFactoryImpl.getInstance().createProducer(Destination.topic("example"), config);

      DemoObject demoObj = new DemoObject();
      if (count <= 0) {
         System.out.println(producer.sendMessage(demoObj));
         Thread.sleep(freq < 0 ? 0 : freq);
      } else {
         for (int i = 0; i < count; i++) {
            demoObj.setA(i);
            System.out.println(producer.sendMessage(demoObj));
            Thread.sleep(freq < 0 ? 0 : freq);
         }
      }
   }

   public static void asyncSendSome(Object content, int count, int freq, Map<String, String> properties, String type)
         throws Exception {
      ProducerConfig config = new ProducerConfig();
      config.setMode(ProducerMode.ASYNC_MODE);
      config.setAsyncRetryTimes(3);
      config.setSendMsgLeftLastSession(false);
      config.setThreadPoolSize(2);
      config.setZipped(false);

      Producer producer = ProducerFactoryImpl.getInstance().createProducer(Destination.topic("whoisyoudadandwhoisyourmomand"), config);
      long begin = System.currentTimeMillis();
      if (count <= 0) {
         while (true) {
            producer.sendMessage(content, properties, type);
            Thread.sleep(freq < 0 ? 0 : freq);
         }
      } else {
         for (int i = 0; i < count; i++) {
//            producer.sendMessage(content, properties, type);
            producer.sendMessage(content);
//            Thread.sleep(freq < 0 ? 0 : freq);
         }
         System.out.println("total cost: " + (System.currentTimeMillis() - begin));
      }
   }

   public static void main(String[] args) throws Exception {

      String content = "";
      for (int i = 0; i < 10; i++) {
         content += "abcdefghij1234567890!@#$%^&*()          abcdefghij1234567890!@#$%^&*()          abcdefghij1234567890";
      }
      SingleThreadSend.syncSendSome(content, -1, 1000, null, null);
      //      SingleThreadSend.syncSendSomeObjectDemoWithZipped(1000, 1000);
//            SingleThreadSend.asyncSendSome(content, -1, 1000, null, null);
   }
}
