#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################


import smtpd
import asyncore
import logging

from email import message_from_string
from email.header import decode_header

########################################

def updateVar(name, value, folder):
    if name not in indigo.variables:
        indigo.variable.create(name, value=value, folder=folder)
    else:
        indigo.variable.updateValue(name, value)

########################################

class CustomSMTPServer(smtpd.SMTPServer):

    def process_message(self, peer, mailfrom, rcpttos, data):
        print 'Receiving message from:', peer
        print 'Message addressed from:', mailfrom
        print 'Message addressed to  :', rcpttos
        print 'Message length        :', len(data)

        message = message_from_string(data)
        
        bytes, encoding = decode_header(message.get("To"))[0]
        if encoding:
            messageTo = bytes.decode(encoding)
        else:
            messageTo = message.get("To")

        bytes, encoding = decode_header(message.get("From"))[0]
        if encoding:
            messageFrom = bytes.decode(encoding)
        else:
            messageFrom = message.get("From")

        bytes, encoding = decode_header(message.get("Subject"))[0]
        if encoding:
            messageSubject = bytes.decode(encoding)
        else:
            messageSubject = message.get("Subject")
        
        try:
            if message.is_multipart():
                part0 = message.get_payload(0)      # we only look at the first alternative content part
                charset = part0.get_content_charset()
                if charset:
                    messageText = part0.get_payload(decode=True).decode(charset)
                else:
                    messageText = part0.get_payload()
            else:
                charset = message.get_content_charset()
                if charset:
                    messageText = message.get_payload(decode=True).decode(charset)
                else:
                    messageText = message.get_payload()

        except Exception, e:
            indigo.activePlugin.debugLog('Error decoding Body of Message # ' + messageNum + ": " + str(e))
            messageText = u""   

        indigo.activePlugin.debugLog(u"Received Message To: " + messageTo)
        indigo.activePlugin.debugLog(u"Received Message From: " + messageFrom)
        indigo.activePlugin.debugLog(u"Received Message Subject: " + messageSubject)
        indigo.activePlugin.debugLog(u"Received Message Text: " + messageText)
        
        updateVar("smtpd_messageTo",      messageTo,      indigo.activePlugin.pluginPrefs["folderId"])
        updateVar("smtpd_messageFrom",    messageFrom,    indigo.activePlugin.pluginPrefs["folderId"])
        updateVar("smtpd_messageSubject", messageSubject, indigo.activePlugin.pluginPrefs["folderId"])
        updateVar("smtpd_messageText",    messageText,    indigo.activePlugin.pluginPrefs["folderId"])

        indigo.activePlugin.triggerCheck()

        self.lines = None
        return defer.succeed(None)
    

################################################################################
class Plugin(indigo.PluginBase):
                    
    ########################################
    # Main Plugin methods
    ########################################
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
        
        pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(msg)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(pfmt)

        try:
            self.logLevel = int(self.pluginPrefs[u"logLevel"])
        except:
            self.logLevel = logging.INFO
        self.indigo_log_handler.setLevel(self.logLevel)
        self.logger.debug(u"logLevel = " + str(self.logLevel))


    def startup(self):
        indigo.server.log(u"Starting SMTPd")
        
        if "SMTPd" in indigo.variables.folders:
            myFolder = indigo.variables.folders["SMTPd"]
        else:
            myFolder = indigo.variables.folder.create("SMTPd")
        self.pluginPrefs["folderId"] = myFolder.id

        self.triggers = { }

        port = int(self.pluginPrefs.get('smtpPort', '2525'))

        self.server = CustomSMTPServer(('', port), None)

    def shutdown(self):
        indigo.server.log(u"Shutting down SMTPd")
        

    def runConcurrentThread(self):
        

        try:
            while True:
                asyncore.loop(timeout=1, count=5)
                self.sleep(0.1)
                
        except self.StopThread:
            pass 

        
    

    ####################

    def triggerStartProcessing(self, trigger):
        self.debugLog("Adding Trigger %s (%d) - %s" % (trigger.name, trigger.id, trigger.pluginTypeId))
        assert trigger.id not in self.triggers
        self.triggers[trigger.id] = trigger
 
    def triggerStopProcessing(self, trigger):
        self.debugLog("Removing Trigger %s (%d)" % (trigger.name, trigger.id))
        assert trigger.id in self.triggers
        del self.triggers[trigger.id] 
        
    def triggerCheck(self):
        for triggerId, trigger in sorted(self.triggers.iteritems()):
            self.debugLog("\tChecking Trigger %s (%s), Type: %s" % (trigger.name, trigger.id, trigger.pluginTypeId))
            if trigger.pluginTypeId == 'messageReceived':
                indigo.trigger.execute(trigger)
            
    
    ####################
    def validatePrefsConfigUi(self, valuesDict):
        self.debugLog(u"validatePrefsConfigUi called")
        errorDict = indigo.Dict()

        smtpPort = int(valuesDict['smtpPort'])
        if smtpPort < 1024:
            errorDict['smtpPort'] = u"SMTP Port Number invalid"

        if len(errorDict) > 0:
            return (False, valuesDict, errorDict)
        return (True, valuesDict)

    ########################################
    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            try:
                self.logLevel = int(valuesDict[u"logLevel"])
            except:
                self.logLevel = logging.INFO
            self.indigo_log_handler.setLevel(self.logLevel)
            self.logger.debug(u"logLevel = " + str(self.logLevel))


    ########################################
    # Menu Methods
    ########################################

            