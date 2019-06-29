#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################


import base64
import logging
import errno
import time
import socket
import asyncore
import asynchat


from email import message_from_string
from email.header import decode_header

########################################

def updateVar(name, value, folder):
    if name not in indigo.variables:
        indigo.variable.create(name, value=value, folder=folder)
    else:
        indigo.variable.updateValue(name, value)

########################################

class SMTPChannel(asynchat.async_chat):
    COMMAND = 0
    DATA = 1
    USERNAME = 2
    PASSWORD = 3
    
    def __init__(self, server, conn, addr):
        asynchat.async_chat.__init__(self, conn)
        self.__server = server
        self.__conn = conn
        self.__addr = addr
        self.__line = []
        self.__state = self.COMMAND
        self.__greeting = 0
        self.__mailfrom = None
        self.__rcpttos = []
        self.__data = ''
        self.__username = None
        
        self.__fqdn = socket.getfqdn()
        try:
            self.__peer = conn.getpeername()
        except socket.error, err:
            # a race condition  may occur if the other end is closing
            # before we can get the peername
            self.close()
            if err[0] != errno.ENOTCONN:
                raise
            return
        self.push('220 {} Indigo SMTPd plugin version {}'.format(self.__fqdn, indigo.activePlugin.pluginVersion))
        self.set_terminator('\r\n')

    def push(self, msg):
        indigo.activePlugin.debugLog('Sending: {}'.format(msg))
        asynchat.async_chat.push(self, msg + '\r\n')

    def collect_incoming_data(self, data):
        self.__line.append(data)

    def found_terminator(self):
        line = ''.join(self.__line)
        indigo.activePlugin.debugLog('Received: {}'.format(repr(line)))
        
        self.__line = []
        if self.__state == self.COMMAND:
            if not line:
                self.push('500 Error: bad syntax')
                return
            method = None
            i = line.find(' ')
            if i < 0:
                command = line.upper()
                arg = None
            else:
                command = line[:i].upper()
                arg = line[i+1:].strip()
            method = getattr(self, 'smtp_' + command, None)
            if not method:
                self.push('502 Error: command "{}" not implemented'.format(command))
                return
            method(arg)
            return

        elif self.__state == self.USERNAME:

            self.__username = base64.decodestring(line)
            indigo.activePlugin.debugLog('Username: {}'.format(self.__username))
            
            self.push('334 UGFzc3dvcmQ6')
            self.__state = self.PASSWORD

        elif self.__state == self.PASSWORD:
            
            password = base64.decodestring(line)
            indigo.activePlugin.debugLog('Password: {}'.format(password))

            if self.__server.validate_auth(self.__username, password):
                self.push('235 Authentication succeeded')
            else:
                self.push('535 Authentication failed')

            self.__state = self.COMMAND
           
        else:
            if self.__state != self.DATA:
                self.push('451 Internal confusion')
                return
                
            # Remove extraneous carriage returns and de-transparency according to RFC 821, Section 4.5.2.
            data = []
            for text in line.split('\r\n'):
                if text and text[0] == '.':
                    data.append(text[1:])
                else:
                    data.append(text)
            self.__data = '\n'.join(data)
            self.__server.process_message(self.__peer, self.__mailfrom, self.__rcpttos, self.__data)
            self.__rcpttos = []
            self.__mailfrom = None
            self.__state = self.COMMAND
            self.set_terminator('\r\n')
            self.push('250 Ok')

    def smtp_HELO(self, arg):

        if not arg:
            self.push('501 Syntax: HELO hostname')
            return
        if self.__greeting:
            self.push('503 Duplicate HELO/EHLO')
        else:
            self.__greeting = arg
            self.push('250 {}'.format(self.__fqdn))

    def smtp_AUTH(self, arg):

        if not arg:
            self.push('501 Syntax: AUTH LOGIN')
            self.__state = self.COMMAND

        elif arg == 'LOGIN':
            self.push('334 VXNlcm5hbWU6')
            self.__state = self.USERNAME

        elif arg[0:5] == 'PLAIN':
            id, username, password = base64.decodestring(arg[6:]).split('\0')
            
            indigo.activePlugin.debugLog('Username: {}'.format(username))
            indigo.activePlugin.debugLog('Password: {}'.format(password))
            
            if self.__server.validate_auth(username, password):
                self.push('235 Authentication succeeded')
            else:
                self.push('535 Authentication failed')
            self.__state = self.COMMAND

        else:
            self.push('535 Unsupported AUTH method')
            self.__state = self.COMMAND
        

    def smtp_NOOP(self, arg):

        if arg:
            self.push('501 Syntax: NOOP')
        else:
            self.push('250 Ok')

    def smtp_QUIT(self, arg):

        # args is ignored
        self.push('221 Bye')
        self.close_when_done()

    # factored
    def __getaddr(self, keyword, arg):
        address = None
        keylen = len(keyword)
        if arg[:keylen].upper() == keyword:
            address = arg[keylen:].strip()
            if not address:
                pass
            elif address[0] == '<' and address[-1] == '>' and address != '<>':
                # Addresses can be in the form <person@dom.com> but watch out
                # for null address, e.g. <>
                address = address[1:-1]
        return address

    def smtp_MAIL(self, arg):

        address = self.__getaddr('FROM:', arg) if arg else None
        if not address:
            self.push('501 Syntax: MAIL FROM:<address>')
            return
        if self.__mailfrom:
            self.push('503 Error: nested MAIL command')
            return
        self.__mailfrom = address
        self.push('250 Ok')

    def smtp_RCPT(self, arg):
        
        if not self.__mailfrom:
            self.push('503 Error: need MAIL command')
            return
        address = self.__getaddr('TO:', arg) if arg else None
        if not address:
            self.push('501 Syntax: RCPT TO: <address>')
            return
        self.__rcpttos.append(address)
        self.push('250 Ok')

    def smtp_RSET(self, arg):

        if arg:
            self.push('501 Syntax: RSET')
            return
        # Resets the sender, recipients, and data, but not the greeting
        self.__mailfrom = None
        self.__rcpttos = []
        self.__data = ''
        self.__state = self.COMMAND
        self.push('250 Ok')

    def smtp_DATA(self, arg):

        if not self.__rcpttos:
            self.push('503 Error: need RCPT command')
            return
        if arg:
            self.push('501 Syntax: DATA')
            return
        self.__state = self.DATA
        self.set_terminator('\r\n.\r\n')
        self.push('354 End data with <CR><LF>.<CR><LF>')

################################################################################

class SMTPServer(asyncore.dispatcher):

    def __init__(self, port, username, password):

        self.username = username
        self.password = password
        
        asyncore.dispatcher.__init__(self)
        try:
            self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
            # try to re-use a server port if possible
            self.set_reuse_addr()
            self.bind(('', port))
            self.listen(5)
        except:
            # cleanup asyncore.socket_map before raising
            self.close()
            raise
        else:
            indigo.activePlugin.debugLog('{} started on: {}'.format(self.__class__.__name__, port))

    def handle_accept(self):
        indigo.activePlugin.debugLog('SMTPServer.handle_accept()')
        pair = self.accept()
        if pair is not None:
            conn, addr = pair
            indigo.activePlugin.debugLog('Incoming connection from {}'.format(repr(addr)))
            channel = SMTPChannel(self, conn, addr)

    def validate_auth(self, username, password):
        indigo.activePlugin.debugLog('SMTPServer.validate_auth({}, {})'.format(username, password))
    
        if self.username == username and self.password == password:
            return True
        else:
            return False
        
    def process_message(self, peer, mailfrom, rcpttos, data):
        indigo.activePlugin.debugLog('SMTPServer.process_message()')
        indigo.activePlugin.debugLog('Receiving message from: {}'.format(peer))
        indigo.activePlugin.debugLog('Message addressed from: {}'.format(mailfrom))
        indigo.activePlugin.debugLog('Message addressed to  : {}'.format(rcpttos))
        indigo.activePlugin.debugLog('Message length        : {}'.format(len(data)))

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

        indigo.activePlugin.debugLog(u"Received Message To: {}".format(messageTo))
        indigo.activePlugin.debugLog(u"Received Message From: {}".format(messageFrom))
        indigo.activePlugin.debugLog(u"Received Message Subject: {}".format(messageSubject))
        indigo.activePlugin.debugLog(u"Received Message Text: {}".format(messageText))
        
        updateVar("smtpd_messageTo",      messageTo,      indigo.activePlugin.pluginPrefs["folderId"])
        updateVar("smtpd_messageFrom",    messageFrom,    indigo.activePlugin.pluginPrefs["folderId"])
        updateVar("smtpd_messageSubject", messageSubject, indigo.activePlugin.pluginPrefs["folderId"])
        updateVar("smtpd_messageText",    messageText,    indigo.activePlugin.pluginPrefs["folderId"])

        indigo.activePlugin.triggerCheck()

        self.lines = None


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
        username = self.pluginPrefs.get('smtpUser', 'guest')
        password = self.pluginPrefs.get('smtpPassword', 'password')

        self.server = SMTPServer(port, username, password)

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

            