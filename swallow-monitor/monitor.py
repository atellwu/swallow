# monitor.py
# coding=gbk

from email.mime.text import MIMEText
import MonitorConfig
import httplib
import json
import logging
import pymongo
import sets
import smtplib
import sys
import time
import urllib
from bson.timestamp import Timestamp

# Monitor config
config = MonitorConfig.MonitorConfig()

shouldNotify = False
alarmSms = str()

# CAT������ַ�������ִ�
CAT_HOST = '10.1.6.128:8080'
CAT_URL = '/cat/r/dashboard?'

# ʹ��ProducerClient����ĿDomain���Ƽ���
producerClientDomain = sets.Set()

# ���������ѣ���������������ӳ�䣬��Server�˻�ȡ����
producedMap = dict()
consumedMap = dict()

# Consumer servers stat
consumerServerStat = dict()

# �����ȡ��������
producerServerInfos = sets.Set()
consumerServerInfos = sets.Set()
cumulatedInfos = sets.Set()
producerClientInfos = sets.Set()
producerAsyncCumulatedInfos = sets.Set()
asyncFailedInfos = sets.Set()
syncFailedInfos = sets.Set()
consumerClientInfos = sets.Set()
mongoInfos = sets.Set()
mongoStatInfos = sets.Set()
mongoConsumeStatInfos = sets.Set()

# �����־
logger = logging.getLogger()
loggerFileHandler = logging.FileHandler('/data/applogs/swallow/swallow-monitor.log')
loggerFormatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
loggerFileHandler.setFormatter(loggerFormatter)
logger.addHandler(loggerFileHandler)
logger.setLevel(logging.NOTSET)

class ProducerServerInfo:
    def __init__(self, ip=str(), topicName=str(), received=str(), failed=str(), avgSpeed=str()):
        self.ip = ip
        self.topicName = topicName
        self.received = received
        self.failed = failed
        self.avgSpeed = avgSpeed
    def __repr__(self):
        return 'ip=' + self.ip + '; topicName=' + self.topicName + '; received=' + self.received + '; failed=' + self.failed + '; avgSpeed=' + self.avgSpeed
    def key(self):
        return str(self.ip) + str(self.topicName)

class ConsumerServerInfo:
    def __init__(self, ip=str(), topicName=str(), cid=str(), pushed=str(), avgSpeed=str()):
        self.ip = ip
        self.topicName = topicName
        self.cid = cid
        self.pushed = pushed
        self.avgSpeed = avgSpeed
    def __repr__(self):
        return 'ip=' + self.ip + ';topicName=' + self.topicName + '; cid=' + self.cid + '; pushed=' + self.pushed + '; avgSpeed=' + self.avgSpeed
    def key(self):
        return str(self.ip) + str(self.topicName) + str(self.cid)
         
class CumulatedInfo:
    def __init__(self, topicName=str(), produced=str(), consumed=str()):
        self.topicName = topicName
        self.produced = produced
        self.consumed = consumed
    def __repr__(self):
        return 'topicName=' + self.topicName + '; produced=' + self.produced + '; consumed=' + self.consumed
    def key(self):
        return self.topicName

class ProducerClientInfo:
    def __init__(self, ip=str(), topicName=str(), produced=int(), failed=int()):
        self.ip = ip
        self.topicName = topicName
        self.produced = produced
        self.failed = failed
    def __repr__(self):
        return 'ip=' + self.ip + '; topicName=' + self.topicName + '; produced=' + str(self.produced) + '; failed=' + str(self.failed)
    def key(self):
        return str(self.ip) + str(self.topicName)

class ConsumerClientInfo:
    def __init__(self, ip=str(), topicName=str(), cid=str(), received=str(), failed=str()):
        self.ip = ip
        self.topicName = topicName
        self.cid = cid
        self.received = received
        self.failed = failed
    def __repr__(self):
        return 'ip=' + self.ip + '; topicName=' + self.topicName + '; cid=' + self.cid + '; received=' + self.received + '; failed=' + self.failed
    def key(self):
        return str(self.ip) + str(self.topicName) + str(self.cid)

class ProducerAsyncCumulatedInfo:
    def __init__(self, ip=str(), topic=str(), count=0, times=0):
        self.ip = ip
        self.topic = topic
        self.cumulated = count * times
        self.times = times
    def addCumulated(self, count, times):
        if count > 0 and times > 0:
            self.cumulated += count * times
            self.times += times
    def __repr__(self):
        return 'ip=' + self.ip + '; topic=' + self.topic + '; cumulated=' + str(self.cumulated) + '; avgCumulated=' + str(self.cumulated * 1.0 / self.times)
    def key(self):
        return str(self.ip) + str(self.topic)

class AsyncFailedInfo:
    def __init__(self, ip=str(), topicName=str(), failed=str()):
        self.ip = ip
        self.topicName = topicName
        self.failed = failed
    def __repr__(self):
        return 'ip=' + self.ip + '; topicName=' + self.topicName + '; failed=' + self.failed
    def key(self):
        return str(self.ip) + str(self.topicName)

class SyncFailedInfo:
    def __init__(self, ip=str(), topicName=str(), failed=str()):
        self.ip = ip
        self.topicName = topicName
        self.failed = failed
    def __repr__(self):
        return 'ip=' + self.ip + '; topicName=' + self.topicName + '; failed=' + self.failed
    def key(self):
        return str(self.ip) + str(self.topicName)

class MongoInfo:
    def __init__(self, consumerId=str(), topic=str(), producedMax=None, consumedMax=None, delayTime=0):
        self.consumerId = consumerId
        self.topic = topic
        self.producedMax = producedMax
        self.consumedMax = consumedMax
        self.delayTime = delayTime
    def __repr__(self):
        return 'topic=' + self.topic + '; consumerId=' + self.consumerId + '; producedMax=' + str(self.producedMax) + '; consumedMax=' + str(self.consumedMax) + '; delayTime=' + str(self.delayTime)
    def key(self):
        return str(self.topic) + str(self.consumerId)

class MongoStatInfo:
    topicName = str()
    lastPeriodAmount = int()
    def __repr__(self):
        return 'topicName=' + self.topicName + '; lastPeriodAmount=' + str(self.lastPeriodAmount)
    def key(self):
        return self.topicName
    
class MongoConsumedStatInfo:
    topicName = str()
    consumerId = str()
    lastPeriodAmount = int()
    def __repr__(self):
        return 'topicName=' + self.topicName + '; consumerId=' + self.consumerId + '; lastPeriodAmount=' + str(self.lastPeriodAmount)
    def key(self):
        return self.topicName + str(self.lastPeriodAmount)

class SMS:
    def __init__(self, phoneNum=str(), message=str()):
        self.phoneNum = phoneNum
        self.message = message
    def __repr__(self):
        return 'phoneNumber=' + self.phoneNum + '; message=' + self.message

# ��ȡProducerServer��consumerServer�˵�����
def getServerInfo():
    conn = httplib.HTTPConnection(CAT_HOST)
    conn.request('GET', CAT_URL + 'domain=Swallow&report=transaction')
    
    try:
        datas = json.loads(conn.getresponse().read().strip())
    except:
        logger.error('[SwallowServer] Get Types from Swallow failed.')
#        print ('[SwallowServer] Get Types from Swallow failed.')
        conn.close()
        return False

    for data in datas:
        
        # ProducerServer���ݻ�ȡ
        if data.startswith('In:'):
            if not checkType(data):
                continue
            topicName = data[3:len(data) - 5]
            
            try:
                if datas.__contains__('In:' + topicName + 'FailureCount'):
                    producedMap[topicName] = int(datas[data]) - int(datas['In:' + topicName + 'FailureCount'])
                else:
                    producedMap[topicName] = int(datas[data])
            except:
                producedMap[topicName] = -1
            
            conn.request('GET', CAT_URL + 'domain=Swallow&report=transaction&type=' + 'In:' + topicName)
            try:
                names = json.loads(conn.getresponse().read().strip())
            except:
                logger.error('[ProducerServer] Get Names from ' + 'In:' + topicName + ' failed.')
#                print ('[ProducerServer] Get Names from ' + 'In:' + topicName + ' failed.')
                continue
            
            for name in names:
                if checkName(name):
                    tmpStr = name[:len(name) - 5]
                    domainAndIp = str(tmpStr).split(':')
                    producerClientDomain.add(domainAndIp[0]);
                    
                    psInfo = ProducerServerInfo()
                    psInfo.ip = domainAndIp[1]
                    psInfo.topicName = topicName
                    psInfo.received = names[name]
                    psInfo.failed = names[tmpStr + 'FailureCount']
                    psInfo.avgSpeed = names[tmpStr + 'ResponseTime']
                    producerServerInfos.add(psInfo)
        
        # ConsumerServer���ݻ�ȡ
        elif(data.startswith('Out:')):
            if not checkType(data):
                continue
            topicName = data[4:len(data) - 5]
            
            try:
                if(datas.__contains__('Out:' + topicName + 'FailureCount')):
                    consumedMap[topicName] = int(datas[data]) - int(datas['Out:' + topicName + 'FailureCount'])
                else:
                    consumedMap[topicName] = int(datas[data])
            except:
                consumedMap[topicName] = -1
            
            conn.request('GET', CAT_URL + 'domain=Swallow&report=transaction&type=' + 'Out:' + topicName)
            try:
                names = json.loads(conn.getresponse().read().strip())
            except:
                logger.error('[ConsumerServer] Get Names from ' + 'Out:' + topicName + ' failed.')
#                print ('[ConsumerServer] Get Names from ' + 'Out:' + topicName + ' failed.')
                continue

            for name in names:
                if checkName(name):
                    tmpStr = name[:len(name) - 5]
                    cidAndIp = str(tmpStr).split(':')
                    
                    csInfo = ConsumerServerInfo()
                    csInfo.ip = cidAndIp[1]
                    csInfo.topicName = topicName
                    csInfo.cid = cidAndIp[0]
                    csInfo.pushed = names[name]
                    csInfo.avgSpeed = names[tmpStr + 'ResponseTime']
                    consumerServerInfos.add(csInfo)
    conn.close()
    return True

def checkType(data):
    if not data.endswith('Count'):
        return False
    elif data.endswith('FailureCount'):
        return False
    else:
        return True

def checkName(name):
    if not name.endswith('Count'):
        return False
    elif name.endswith('FailureCount'):
        return False
    elif len(name) == 5:
        return False
    else:
        return True

# ��Server�˻�ȡ�ѻ�����
def getCumulatedInfo():
    if len(producedMap) == 0 and len(consumedMap) == 0:
        logger.warning('[CumulateSummary] No message produced or consumed.')
#        print ('[CumulateSummary] No message produced or consumed.')
        return
    for topicName, amount in producedMap.items():
        cInfo = CumulatedInfo()
        cInfo.topicName = topicName
        cInfo.produced = str(amount)
        cInfo.consumed = str(consumedMap[topicName]) if consumedMap.has_key(topicName) else '0'
        cumulatedInfos.add(cInfo)

# ��ȡProducerClient��ͳ������
def getProducerClientInfo():
    for domain in config.domainProducerReject:
        domainStr = str(domain).strip()
        if len(domainStr) < 1:
            continue
        if domainStr == 'All':
            producerClientDomain.clear()
            break
        elif producerClientDomain.__contains__(domainStr):
            producerClientDomain.remove(domainStr)

    if len(producerClientDomain) == 0:
        logger.warning('[ProducerClient] No ProducerClient Domains found.')
#        print ('[ProducerClient] No ProducerClient Domains found.')
        return
    
    for domain in producerClientDomain:
        conn = httplib.HTTPConnection(CAT_HOST)
        conn.request('GET', CAT_URL + 'domain=' + domain + '&report=transaction')
        try:
            types = json.loads(conn.getresponse().read().strip())
        except:
            logger.error('[ProducerClient] Get Types from ' + domain + ' failed.')
#            print ('[ProducerClient] Get Types from ' + domain + ' failed.')
            conn.close()
            continue

        # ��ȡAsyncģʽProducer����ʧ������
        if types.__contains__('MsgAsyncFailedCount'):
            conn.request('GET', CAT_URL + 'domain=' + domain + '&report=transaction&type=MsgAsyncFailed')
            try:
                names = json.loads(conn.getresponse().read().strip())
                for name in names:
                    if checkName(name):
                        tmpStr = name[:len(name) - 5]
                        topicAndIp = str(tmpStr).split(':')
                        
                        afInfo = AsyncFailedInfo()
                        afInfo.ip = topicAndIp[1]
                        afInfo.topicName = topicAndIp[0]
                        afInfo.failed = names[name]
                        asyncFailedInfos.add(afInfo)
            except:
                logger.error('[ProducerClient] Get Names from domain=' + domain + ' type=MsgAsyncFailed failed.')
#                print ('[ProducerClient] Get Names from domain=' + domain + ' type=MsgAsyncFailed failed.')
                
        
        # ��ȡSyncģʽProducer����ʧ������
        if types.__contains__('MsgSyncFailedCount'):
            conn.request('GET', CAT_URL + 'domain=' + domain + '&report=transaction&type=MsgSyncFailed')
            try:
                names = json.loads(conn.getresponse().read().strip())
                for name in names:
                    if checkName(name):
                        tmpStr = name[:len(name) - 5]
                        topicAndIp = str(tmpStr).split(':')
                        
                        sfInfo = AsyncFailedInfo()
                        sfInfo.ip = topicAndIp[1]
                        sfInfo.topicName = topicAndIp[0]
                        sfInfo.failed = names[name]
                        syncFailedInfos.add(sfInfo)
            except:
                logger.error('[ProducerClient] Get Names from domain=' + domain + ' type=MsgSyncFailed failed.')
#                print ('[ProducerClient] Get Names from domain=' + domain + ' type=MsgSyncFailed failed.')
                    
        # ��ȡFilequeue�ѻ�����
        if types.__contains__('SwallowHeartbeatCount'):
            conn.request('GET', CAT_URL + 'domain=' + domain + '&report=transaction&type=SwallowHeartbeat')
            try:
                names = json.loads(conn.getresponse().read().strip())
                for name in names:
                    if checkName(name):
                        tmpStr = name[:len(name) - 5]
                        ipAndTopicAndCount = str(tmpStr).split(':')

                        exist = False
                        for pacInfo in producerAsyncCumulatedInfos:
                            if pacInfo.ip == str(ipAndTopicAndCount[0]).strip() and pacInfo.topic == str(ipAndTopicAndCount[1]).strip():
                                if int(ipAndTopicAndCount[2]) > 0:
                                    pacInfo.addCumulated(int(ipAndTopicAndCount[2]), int(names[name]))
                                exist = True
                                break;
                        if not exist:
                            if int(ipAndTopicAndCount[2]) > 0:
                                pacInfo = ProducerAsyncCumulatedInfo(ipAndTopicAndCount[0], ipAndTopicAndCount[1], int(ipAndTopicAndCount[2]), int(names[name]))
                            else:
                                pacInfo = ProducerAsyncCumulatedInfo(ipAndTopicAndCount[0], ipAndTopicAndCount[1], 0, int(names[name]))
                            producerAsyncCumulatedInfos.add(pacInfo)
            except:
                logger.error('[ProducerClient] Get Names from domain=' + domain + ' type=SwallowHeartbeat failed.')
#                print ('[ProducerClient] Get Names from domain=' + domain + ' type=SwallowHeartbeat failed.')

        # ��ȡProducerClient�����������
        conn.request('GET', CAT_URL + 'domain=' + domain + '&report=transaction&type=MsgProduced')
        try:
            names = json.loads(conn.getresponse().read().strip())
            for name in names:
                if checkName(name):
                    tmpStr = name[:len(name) - 5]
                    topicAndIp = str(tmpStr).split(':')

                    pcInfo = ProducerClientInfo()
                    pcInfo.ip = topicAndIp[1]
                    pcInfo.topicName = topicAndIp[0]
                    pcInfo.produced = names[name]
                    pcInfo.failed = names[tmpStr + 'FailureCount']
                    producerClientInfos.add(pcInfo)
        except:
            logger.error('[ProducerClient] Get Names from domain=' + domain + ' type=MsgProduced failed.')
#            print ('[ProducerClient] Get Names from domain=' + domain + ' type=MsgProduced failed.')

        conn.close()

# ��ȡConsumerClient������
def getConsumerClientInfo():

    for domain in config.domainConsumerAccept:
        domainStr = str(domain).strip()
        if len(domainStr) <= 1:
            continue
        conn = httplib.HTTPConnection(CAT_HOST)
        conn.request('GET', CAT_URL + 'domain=' + domainStr + '&report=transaction&type=MsgConsumed')

        try:
            names = json.loads(conn.getresponse().read().strip())
        except:
            logger.error('[ConsumerClient] Get Names from domain=' + domain + ' type=MsgConsumed failed.')
#            print ('[ConsumerClient] Get Names from domain=' + domain + ' type=MsgConsumed failed.')
            conn.close()
            continue
            
        for name in names:
            if checkName(name):
                tmpStr = name[:len(name) - 5]
                topicAndCidAndIp = str(tmpStr).split(':')
                
                ccInfo = ConsumerClientInfo()
                ccInfo.ip = topicAndCidAndIp[2]
                ccInfo.topicName = topicAndCidAndIp[0]
                ccInfo.cid = topicAndCidAndIp[1]
                ccInfo.received = names[name]
                ccInfo.failed = names[tmpStr + 'FailureCount']
                consumerClientInfos.add(ccInfo)
        conn.close()

# ��mongo��ȡ��Ϣ
def getMongoInfos():
    for uri in config.mongoMongoUri:
        uristr = str(uri).strip()
        if len(uristr) <= 1:
            continue
        
        try:
            conn = pymongo.ReplicaSetConnection(uristr, replicaSet='SwallowCap')
#            conn.read_preference = pymongo.read_preferences.ReadPreference.SECONDARY_PREFERRED
            conn.read_preference = pymongo.ReadPreference.SECONDARY
        except:
            logger.error('[MongoInfo] Connect to ' + uristr + ' in replicaSet = SwallowCap failed. Try Normal connect.')
#            print ('[MongoInfo] Connect to ' + uristr + ' in replicaSet = SwallowCap failed. Try Nomal connect.')
            try:
                conn = pymongo.Connection(uri)
            except:
                logger.error('[MongoInfo] Connect to ' + uristr + ' failed.')
#                print ('[MongoInfo] Connect to ' + uristr + ' failed.')
                continue
        
        names = conn.database_names()
        MPMap = dict()
        for name in names:
            if str(name).startswith('msg#'):
                domains = str(name).split('#')
                topic = domains[1]
                info = next(conn[name]['c'].find().sort('_id', -1).limit(1), None)
                
                # �������룬����Ѿ���¼����topic�ϴ�������Ϣ�����������˶�������Ϣ�����򽫸�topic������Ϊ�����˶�������Ϣ
                if(config.logMongoTopic.__contains__(topic.lower())):
                    lastPeroidCount = conn[name]['c'].find({'_id' : {'$gt' : config.logMongoTopic[topic.lower()]}}).count()
                else:
                    lastPeroidCount = conn[name]['c'].count()
                    
                mongoStatInfo = MongoStatInfo()
                mongoStatInfo.topicName = topic
                mongoStatInfo.lastPeriodAmount = lastPeroidCount
                mongoStatInfos.add(mongoStatInfo)
                # ��������
                
                if info == None:
                    MPMap[topic] = None
                    config.logMongoTopic[topic.lower()] = Timestamp(int(time.time()), 1)
                else:
                    MPMap[topic] = info['_id']
                    config.logMongoTopic[topic.lower()] = info['_id']
                    
        
        for name in names:
            if str(name).startswith('ack#'):
                domains = str(name).split('#')
                topic = domains[1]
                cid = domains[2]
                info = next(conn[name]['c'].find().sort('_id', -1).limit(1), None)
                
                if info == None:
                    pass
                else:

                    mi = MongoInfo()
                    mi.topic = topic
                    mi.consumerId = cid
                    mid = info['_id']
                    strmid = str(time.ctime(mid.time)) + ' NO.' + str(mid.inc)
                    mi.consumedMax = strmid
                    if MPMap.has_key(topic):
                        mid = MPMap[topic]
                        if mid != None:
                            strmid = str(time.ctime(mid.time)) + ' NO.' + str(mid.inc)
                            mi.producedMax = strmid
                            mi.delayTime = int(mid.time) - int(info['_id'].time)
                        else:
                            mi.producedMax = None
                            mi.delayTime = 0
                    else:
                        mi.producedMax = None
                        mi.delayTime = 0
                    
                    mongoInfos.add(mi)
                    
                    # �������룬����ͳ��mongo��consumer���Ѽ�¼
                    lastPeroidAmount = 0
                    mongoConsumedStatInfo = MongoConsumedStatInfo()
                    
                    if config.logMongoConsumeStatus.__contains__(topic.lower()):
                        if config.logMongoConsumeStatus[topic.lower()].__contains__(cid.lower()):
                            lastPeroidMsgId = config.logMongoConsumeStatus[topic.lower()][cid.lower()]
                            if names.__contains__('msg#' + topic):
                                lastPeroidAmount = conn['msg#' + topic]['c'].find({'_id' : {'$gt' : lastPeroidMsgId, '$lte' : info['_id']}}).count()
                        else:
                            if names.__contains__('msg#' + topic):
                                lastPeroidAmount = conn['msg#' + topic]['c'].find({'_id' : {'$lte': Timestamp(int(info['_id'].time), info['_id'].inc)}}).count()
                    else:
                        if names.__contains__('msg#' + topic):
                            lastPeroidAmount = conn['msg#' + topic]['c'].find({'_id' : {'$lte': Timestamp(int(info['_id'].time), info['_id'].inc)}}).count()
    
                    mongoConsumedStatInfo.consumerId = cid
                    mongoConsumedStatInfo.topicName = topic
                    mongoConsumedStatInfo.lastPeriodAmount = lastPeroidAmount
                    mongoConsumeStatInfos.add(mongoConsumedStatInfo)
                    if not dict(config.logMongoConsumeStatus).__contains__(topic.lower()):
                        config.logMongoConsumeStatus[topic.lower()] = dict()
                    config.logMongoConsumeStatus[topic.lower()][cid.lower()] = info['_id']
                    # ��������
        
        for name in names:
            if str(name).startswith('heartbeat#'):
                ip = str(str(name)[10:]).strip().replace('_', '.')
                if config.consumerServersIp.__contains__(ip):
                    latestMsgId = next(conn[name]['c'].find().sort('_id', -1).limit(1), None)['t']
                    lastHeartbeatTime = int(time.mktime(latestMsgId.timetuple()))
                    now = int(time.time())
                    if now - lastHeartbeatTime > 60 * 60 * 8 + 60:
                        consumerServerStat[ip] = False
                    else:
                        consumerServerStat[ip] = True
        
        MPMap.clear()
        conn.close()

# ��Cat��ȡͳ������
def getInfosFromCat():
    getServerInfo()
    getProducerClientInfo()
    getConsumerClientInfo()
    getCumulatedInfo()

# ��Mongo��ȡͳ������
def getInfosFromMongo():
    getMongoInfos()

# ����ǰ���ݣ�����ProducerClientDomain���ϡ�
def clearInfosFromCat():
    producerServerInfos.clear()
    consumerServerInfos.clear()
    cumulatedInfos.clear()
    producerClientInfos.clear()
    producerAsyncCumulatedInfos.clear()
    asyncFailedInfos.clear()
    syncFailedInfos.clear()
    consumerClientInfos.clear()
    producedMap.clear()
    consumedMap.clear()

# �����Mongo��ȡ��������
def clearInfosFromMongo():
    mongoInfos.clear()

# �ӵ�ǰ���ݲ����ʼ�����
def generateCatMailContent():
    ret = str()
    
    # add producerServer infos
    if len(producerServerInfos) > 0:
        ret += '''\
        <table align="center" frame= "box" width="90%">
            <tbody align="center">
                <tr align="left" colspan="100%"><td><font color="00005f" size="3"><b>Producer Server</b></font></td></tr>
                <tr bgcolor="ffd588"><th>IP</th><th>TopicName</th><th>Received</th><th>SaveFailed</th><th>AvgSpeed</th></tr>
        '''
        colorFlag = True
        psInfos = sorted(producerServerInfos, key=ProducerServerInfo.key)
        for psi in psInfos:
            if not colorFlag:
                ret += '<tr bgcolor="e2e2e2">'
                colorFlag = not colorFlag
            else:
                ret += '<tr>'
                colorFlag = not colorFlag
            ret += \
            '<td>' + psi.ip + '</td>' + \
            '<td>' + psi.topicName + '</td>' + \
            '<td>' + psi.received + '</td>'
            if str(psi.failed).strip() == '0':
                ret += '<td>'
            else:
                ret += '<td bgcolor="ff8282">'
            ret += \
            psi.failed + '</td>' + \
            '<td>' + psi.avgSpeed + '</td>' + \
            '</tr>'
        ret += '</tbody></table><br /><br />'
    
    # add consumerServer infos
    if len(consumerServerInfos) > 0:
        ret += '''\
        <table align="center" frame= "box" width="90%">
            <tbody align="center">
                <tr><td align="left" colspan="100%"><font color="00005f" size="3"><b>Consumer Server</b></font></td></tr>
                <tr bgcolor="ffd588"><th>IP</th><th>TopicName</th><th>ConsumerID</th><th>Pushed</th><th>AvgSpeed</th></tr>       
        '''
        colorFlag = True
        csInfos = sorted(consumerServerInfos, key=ConsumerServerInfo.key)
        for csi in csInfos:
            if not colorFlag:
                ret += '<tr bgcolor="e2e2e2">'
                colorFlag = not colorFlag
            else:
                ret += '<tr>'
                colorFlag = not colorFlag
            ret += \
            '<td>' + csi.ip + '</td>' + \
            '<td>' + csi.topicName + '</td>' + \
            '<td>' + csi.cid + '</td>' + \
            '<td>' + csi.pushed + '</td>' + \
            '<td>' + csi.avgSpeed + '</td>' + \
            '</tr>'
        
        ret += '</tbody></table><br /><br />'
    
    # add producerClient infos
    if len(producerClientInfos) > 0:
        ret += '''\
        <table align="center" frame= "box" width="90%">
            <tbody align="center">
                <tr><td align="left" colspan="100%"><font color="00005f" size="3"><b>Producer Client</b></font></td></tr>
                <tr bgcolor="ffd588"><th>IP</th><th>TopicName</th><th>Produced</th><th>SendFailed</th></tr>
        '''
        colorFlag = True
        pcInfos = sorted(producerClientInfos, key=ProducerClientInfo.key)
        for pci in pcInfos:
            if not colorFlag:
                ret += '<tr bgcolor="e2e2e2">'
                colorFlag = not colorFlag
            else:
                ret += '<tr>'
                colorFlag = not colorFlag
            ret += \
            '<td>' + pci.ip + '</td>' + \
            '<td>' + pci.topicName + '</td>' + \
            '<td>' + pci.produced + '</td>'
            if str(pci.failed).strip() == '0':
                ret += '<td>'
            else:
                ret += '<td bgcolor="ff8282">'
            ret += pci.failed + '</td></tr>'
        
        ret += '</tbody></table><br /><br />'
    
    # add consumerClient infos
    if len(consumerClientInfos) > 0:
        ret += '''\
        <table align="center" frame= "box" width="90%">
            <tbody align="center">
                <tr><td align="left" colspan="100%"><font color="00005f" size="3"><b>Consumer Client</b></font></td></tr>
                <tr bgcolor="ffd588"><th>IP</th><th>TopicName</th><th>ConsumerID</th><th>Received</th><th>ConsumeFailed</th></tr>
        '''
        colorFlag = True
        ccInfos = sorted(consumerClientInfos, key=ConsumerClientInfo.key)
        for cci in ccInfos:
            if not colorFlag:
                ret += '<tr bgcolor="e2e2e2">'
                colorFlag = not colorFlag
            else:
                ret += '<tr>'
                colorFlag = not colorFlag
            ret += \
            '<td>' + cci.ip + '</td>' + \
            '<td>' + cci.topicName + '</td>' + \
            '<td>' + cci.cid + '</td>' + \
            '<td>' + cci.received + '</td>'
            if str(cci.failed).strip() == '0':
                ret += '<td>' 
            else:
                ret += '<td bgcolor="ff8282">'
            ret += cci.failed + '</td></tr>'
        
        ret += '</tbody></table><br /><br />'
    
    # add ProducerAsyncCumulated infos
    if len(producerAsyncCumulatedInfos) > 0:
        ret += '''\
        <table align="center" frame= "box" width="90%">
            <tbody align="center">
                <tr><td align="left" colspan="100%"><font color="00005f" size="3"><b>Producer Async-Mode Cumulated Infos</b></font></td></tr>
                <tr bgcolor="ffd588"><th>IP</th><th>TopicName</th><th>AvgCumulated</th></tr>
        '''
        colorFlag = True
        pacInfos = sorted(producerAsyncCumulatedInfos, key=ProducerAsyncCumulatedInfo.key)
        for paci in pacInfos:
            if not colorFlag:
                ret += '<tr bgcolor="e2e2e2">'
                colorFlag = not colorFlag
            else:
                ret += '<tr>'
                colorFlag = not colorFlag
            ret += \
            '<td>' + paci.ip + '</td>' + \
            '<td>' + paci.topic + '</td>' + \
            '<td>' + str(int(paci.cumulated * 1.0 / paci.times)) + '</td>' + \
            '</tr>'
        
        ret += '</tbody></table><br /><br />'

    # add ProducerAsyncFailed infos
    if len(asyncFailedInfos) > 0:
        ret += '''\
        <table align="center" frame= "box" width="90%">
            <tbody align="center">
                <tr><td align="left" colspan="100%"><font color="00005f" size="3"><b>Producer Async-Mode Failed Infos</b></font></td></tr>
                <tr bgcolor="ffd588"><th>IP</th><th>TopicName</th><th>Failed</th></tr>
        '''
        colorFlag = True
        afInfos = sorted(asyncFailedInfos, key=AsyncFailedInfo.key)
        for afi in afInfos:
            if not colorFlag:
                ret += '<tr bgcolor="e2e2e2">'
                colorFlag = not colorFlag
            else:
                ret += '<tr>'
                colorFlag = not colorFlag
            ret += \
            '<td>' + afi.ip + '</td>' + \
            '<td>' + afi.topicName + '</td>' + \
            '<td>' + afi.failed + '</td>' + \
            '</tr>'
        
        ret += '</tbody></table><br /><br />'
    
    # add ProducerSyncFailed infos
    if len(syncFailedInfos) > 0:
        ret += '''\
        <table align="center" frame= "box" width="90%">
            <tbody align="center">
                <tr><td align="left" colspan="100%"><font color="00005f" size="3"><b>Producer Sync-Mode Failed Infos</b></font></td></tr>
                <tr bgcolor="ffd588"><th>IP</th><th>TopicName</th><th>Failed</th></tr>
        '''
        colorFlag = True
        sfInfos = sorted(syncFailedInfos, key=SyncFailedInfo.key)
        for sfi in sfInfos:
            if not colorFlag:
                ret += '<tr bgcolor="e2e2e2">'
                colorFlag = not colorFlag
            else:
                ret += '<tr>'
                colorFlag = not colorFlag
            ret += \
            '<td>' + sfi.ip + '</td>' + \
            '<td>' + sfi.topicName + '</td>' + \
            '<td>' + sfi.failed + '</td>' + \
            '</tr>'
        
        ret += '</tbody></table><br /><br />'

    # add Cumulated infos
    if len(cumulatedInfos) > 0:
        ret += '''\
        <table align="center" frame= "box" width="90%">
            <tbody align="center">
                <tr><td align="left" colspan="100%"><font color="00005f" size="3"><b>Produce & Consume Summaries</b></font></td></tr>
                <tr bgcolor="ffd588"><th>TopicName</th><th>ProducedTotal</th><th>ConsumedTotal</th></tr>
        '''
        colorFlag = True
        cInfos = sorted(cumulatedInfos, key=CumulatedInfo.key)
        for ci in cInfos:
            if not colorFlag:
                ret += '<tr bgcolor="e2e2e2">'
                colorFlag = not colorFlag
            else:
                ret += '<tr>'
                colorFlag = not colorFlag
            ret += \
            '<td>' + ci.topicName + '</td>' + \
            '<td>' + ci.produced + '</td>'
            if str(ci.consumed).strip() == '0' and str(ci.produced).strip() != '0':
                ret += '<td bgcolor="ff8282">'
            else:
                ret += '<td>'
            ret += ci.consumed + '</td></tr>'
        
        ret += '</tbody></table><br /><br />'

    return ret

def generateMongoMailContent():
    ret = str()
    
    # add Cumulated infos
    if len(mongoInfos) > 0:
        ret += '''\
        <table align="center" frame= "box" width="90%">
            <tbody align="center">
                <tr><td align="left" colspan="100%"><font color="00005f" size="3"><b>MongoDB Summaries</b></font></td></tr>
                <tr bgcolor="ffd588"><th>TopicName</th><th>ConsumerID</th><th>MaxProducedInfo</th><th>MaxConsumedInfo</th><th>DelayTime</th></tr>
        '''
        colorFlag = True
        mInfos = sorted(mongoInfos, key=MongoInfo.key)
        for mi in mInfos:
            if not colorFlag:
                ret += '<tr bgcolor="e2e2e2">'
                colorFlag = not colorFlag
            else:
                ret += '<tr>'
                colorFlag = not colorFlag
            ret += \
            '<td>' + mi.topic + '</td>' + \
            '<td>' + mi.consumerId + '</td>' + \
            '<td align="left">' + str(mi.producedMax) + '</td>' + \
            '<td align="left">' + str(mi.consumedMax)
            if mi.delayTime > config.alarmMailDelay:
                ret += '<td bgcolor="ff8282">'
            else:
                ret += '<td>'
            ret += getDateFromSeconds(mi.delayTime) + '</td></tr>'
        
        ret += '</tbody></table><br /><br />'
    
    # add Produced infos
    if len(mongoStatInfos) > 0:
        ret += '''\
        <table align="center" frame= "box" width="90%">
            <tbody align="center">
                <tr><td align="left" colspan="100%"><font color="00005f" size="3"><b>Last Period Produced</b></font></td></tr>
                <tr bgcolor="ffd588"><th>TopicName</th><th>Amount</th></tr>
        '''
        
        colorFlag = True
        mpInfos = sorted(mongoStatInfos, key=MongoStatInfo.key)
        mi = MongoStatInfo()
        for mi in mpInfos:
            if not colorFlag:
                ret += '<tr bgcolor="e2e2e2">'
                colorFlag = not colorFlag
            else:
                ret += '<tr>'
                colorFlag = not colorFlag
            ret += \
            '<td>' + mi.topicName + '</td>' + \
            '<td>' + str(mi.lastPeriodAmount) + '</td></tr>'
       
        ret += '</tbody></table><br /><br />'
    
    # add Consumed Infos
    if len(mongoConsumeStatInfos) > 0:
        ret += '''\
        <table align="center" frame= "box" width="90%">
            <tbody align="center">
                <tr><td align="left" colspan="100%"><font color="00005f" size="3"><b>Last Period Consumed</b></font></td></tr>
                <tr bgcolor="ffd588"><th>TopicName</th><th>ConsumerID</th><th>Amount</th></tr>
        '''
        
        colorFlag = True
        mcInfos = sorted(mongoConsumeStatInfos, key=MongoConsumedStatInfo.key)
        mi = MongoConsumedStatInfo()
        for mi in mcInfos:
            if not colorFlag:
                ret += '<tr bgcolor="e2e2e2">'
                colorFlag = not colorFlag
            else:
                ret += '<tr>'
                colorFlag = not colorFlag
            ret += \
            '<td>' + mi.topicName + '</td>' + \
            '<td>' + mi.consumerId + '</td>' + \
            '<td>' + str(mi.lastPeriodAmount) + '</td></tr>'

        ret += '</tbody></table><br /><br />'

    if len(consumerServerStat) > 0:
        ret += '''\
        <table align="center" frame= "box" width="90%">
            <tbody align="center">
                <tr><td align="left" colspan="100%"><font color="00005f" size="3"><b>Consumer Server Heartbeat</b></font></td></tr>
                <tr bgcolor="ffd588"><th>Ip Address</th><th>Status</th></tr>
        '''
        
        colorFlag = True
        mpInfos = sorted(consumerServerStat.items())
        for key, value in mpInfos:
            if not colorFlag:
                ret += '<tr bgcolor="e2e2e2">'
                colorFlag = not colorFlag
            else:
                ret += '<tr>'
                colorFlag = not colorFlag
            ret += \
            '<td>' + str(key) + '</td>' + \
            '<td>' + str(value) + '</td></tr>'
       
        ret += '</tbody></table><br /><br />'
    
    return ret

def getDateFromSeconds(seconds):
    aMinute = 60
    anHour = aMinute * 60
    aDay = anHour * 24
    
    days = seconds / aDay
    hours = seconds % aDay / anHour
    mins = seconds % aDay % anHour / aMinute
    secs = seconds % aDay % anHour % aMinute
    
    return str(days) + '-' + str(hours) + '-' + str(mins) + '-' + str(secs)

def generateCatMail():
    content = generateCatMailContent()
    if len(content) == 0:
        return None
    head = '<head><meta http-equiv="Content-Type" content="text/html; charset=UTF-8"></head>'
    body = '<body>' + content + '</body>'
    html = '<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd"><html>' + head + body + '</html>'
    return html

def generateMongoMail():
    content = generateMongoMailContent()
    if len(content) == 0:
        return None
    head = '<head><meta http-equiv="Content-Type" content="text/html; charset=UTF-8"></head>'
    body = '<body>' + content + '</body>'
    html = '<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd"><html>' + head + body + '</html>'
    return html

# ����CatMail
def postCatMail():
    mail = generateCatMail()
    
    if not mail == None:
        msg = MIMEText(mail, 'html')
        msg['Subject'] = '[Swallow] Monitor Informations From Cat'
        msg['From'] = 'Swallow<swallow@dianping.com>'
        
        try:
            s = smtplib.SMTP()
            s.connect('mail.51ping.com')
            s.login('mysql_monitor@51ping.com', 'monitor123')
        except:
            logger.error('[PostMail] Mail service error.')
            return
        
        for mailReceiver in config.mailMailReceiver:
            addr = str(mailReceiver).strip()
            if len(addr) < 1:
                continue
            elif not checkMailAddr(addr):
                continue
            msg['To'] = addr
            s.sendmail('Swallow<swallow@dianping.com>', addr, msg.as_string())
        s.quit()

# ����MongoMail
def postMongoMail():
    mail = generateMongoMail()
    if not mail == None:
        msg = MIMEText(mail, 'html')
        msg['Subject'] = '[Swallow] Monitor Informations From Mongo'
        msg['From'] = 'Swallow<swallow@dianping.com>'
        
        try:
            s = smtplib.SMTP()
            s.connect('mail.51ping.com')
            s.login('mysql_monitor@51ping.com', 'monitor123')
        except:
            logger.error('[PostMail] Mail service error.')
            return

        for mailReceiver in config.mailMailReceiver:
            addr = str(mailReceiver).strip()
            if len(addr) < 1:
                continue
            elif not checkMailAddr(addr):
                continue
            msg['To'] = addr
            s.sendmail('Swallow<swallow@dianping.com>', addr, msg.as_string())
        s.quit()

# ����ʼ���ַ�Ƿ���淶
def checkMailAddr(addr):
    if str(addr).find('@') == -1:
        return False
    domain = (str(addr).split('@'))[1]
    if str(domain).find('.') == -1:
        return False
    return True

def shouldIgnoreInSms(topicName, consumerID):
    if config.smsignoreTopicNames.has_key(topicName):
        if len(config.smsignoreTopicNames[topicName]) == 0:
            return True;
        else:
            if consumerID != None and config.smsignoreTopicNames[topicName].__contains__(consumerID):
                return True;
    return False;

# �����Ƿ�Ӧ�ñ��������ɱ�����������
def analysis():
    global shouldNotify
    global alarmSms
    
    preProduceFailed = config.logPreProduceFailed
    preSaveFailed = config.logPreSaveFailed
    preAsyncCumulated = config.logPreAsyncCumulated
    preSumCumulated = config.logPreSumCumulated
    preSumDelay = config.logPreSumDelay
    
    
    produceFailed = 0
    sfi = SyncFailedInfo()
    for sfi in syncFailedInfos:
        if not shouldIgnoreInSms(sfi.topicName, None):
            produceFailed += int(sfi.failed)
    asfi = AsyncFailedInfo()
    for asfi in asyncFailedInfos:
        if not shouldIgnoreInSms(asfi.topicName, None):
            produceFailed += int(asfi.failed)
    
    saveFailed = 0
    psi = ProducerServerInfo()
    for psi in producerServerInfos:
        if not shouldIgnoreInSms(psi.topicName, None):
            saveFailed += int(psi.failed)
    
    asyncCumulated = 0
    maxAsyncCumulated = 0
    maxAsyncCumulatedIp = ''
    paci = ProducerAsyncCumulatedInfo()
    for paci in producerAsyncCumulatedInfos:
        if not shouldIgnoreInSms(paci.topic, None):
            nowCumulated = int(paci.cumulated * 1.0 / paci.times)
            asyncCumulated += nowCumulated
            if nowCumulated > maxAsyncCumulated:
                maxAsyncCumulated = nowCumulated
                maxAsyncCumulatedIp = paci.ip
            
    sumCumulated = 0
    ci = CumulatedInfo()
    for ci in cumulatedInfos:
        if not shouldIgnoreInSms(ci.topicName, None):
            sumCumulated += int(ci.produced) - int(ci.consumed)
    
    sumDelay = 0
    mi = MongoInfo()
    for mi in mongoInfos:
        if not shouldIgnoreInSms(mi.topic, mi.consumerId):
            sumDelay += int(mi.delayTime)

    alarmSms = '[Swallow]�׶ξ���\n'
    
    if produceFailed - preProduceFailed > config.alarmSmsProduceFailed:
        alarmSms += '����ʧ��(ͬ��+�첽)����: ' + str(produceFailed - preProduceFailed) + '\n'
        shouldNotify = True
    preProduceFailed = produceFailed
    
    if saveFailed - preSaveFailed > config.alarmSmsMongoFailed:
        alarmSms += '����Mongoʧ������: ' + str(saveFailed - preSaveFailed) + '\n'
        shouldNotify = True
    preSaveFailed = saveFailed
    
    if asyncCumulated - preAsyncCumulated > config.alarmSmsCumulateAsync:
        alarmSms += 'FileQ�ѻ�����: ' + str(asyncCumulated - preAsyncCumulated) + '\n'
        alarmSms += '�ѻ�Top1: ' + str(maxAsyncCumulatedIp) + ': ' + str(maxAsyncCumulated) + '\n'
        shouldNotify = True
    preAsyncCumulated = asyncCumulated
    
    if sumCumulated - preSumCumulated > config.alarmSmsCumulateSum:
        alarmSms += '������ǰ����: ' + str(sumCumulated - preSumCumulated) + '\n'
        shouldNotify = True
    preSumCumulated = sumCumulated
    
    if sumDelay - preSumDelay > config.alarmSmsDelaySum:
        alarmSms += '������ʱ�ܼ�(��): ' + getDateFromSeconds(sumDelay - preSumDelay) + '\n'
        shouldNotify = True
    preSumDelay = sumDelay
    
    for key, value in consumerServerStat.items():
        if value == False:
            alarmSms += 'ConsumerServer����: ' + str(key) + '\n'
            shouldNotify = True
    
    config.logPreAsyncCumulated = preAsyncCumulated
    config.logPreProduceFailed = preProduceFailed
    config.logPreSaveFailed = preSaveFailed
    config.logPreSumCumulated = preSumCumulated
    config.logPreSumDelay = preSumDelay
    
# ��alarmSms�����ű������ݣ����͸�ָ����receiver
def postSms():
    if alarmSms != '[Swallow]�׶ξ���\n':
        for phoneNum in config.smsSmsReceiver:
            conn = httplib.HTTPConnection('211.136.163.68:8000');
            smsUrl = '/httpserver?enterpriseid=95102&accountid=000&pswd=z5PgZ4&mobs=' + str(phoneNum) + '&msg=' + urllib.quote(alarmSms);
            conn.request('POST', smsUrl)
            conn.close()

# ��Cat��Mongo�ϻ�ȡ����
def getLatestInfos():
    clearInfosFromCat()
    clearInfosFromMongo()
    
    config.getConfig()
    config.getLog()
    
    getInfosFromCat()
    getInfosFromMongo()

def notify():
    global shouldNotify
    postMongoMail()
    if shouldNotify:
        shouldNotify = False
        postCatMail()
        postSms()
        
def updateLog():
    args = sys.argv
    shouldResetLog = True if len(args) > 1 and str(args[1]).lower() == 'true' else False
    if shouldResetLog:
        config.logPreAsyncCumulated = 0
        config.logPreProduceFailed = 0
        config.logPreSaveFailed = 0
        config.logPreSumCumulated = 0
        config.logPreSumDelay = 0
    config.updateLog()

getLatestInfos()
analysis()
notify()
updateLog()
