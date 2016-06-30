#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import sys
import time
import smtpd
import asyncore
import os
import errno
import socket
import asynchat
import threading

from ghpu import GitHubPluginUpdater

kCurDevVersCount = 0		# current version of plugin devices			

class SMTPChannel(asynchat.async_chat):
	COMMAND = 0
	DATA = 1

	def __init__(self, server, conn, addr):
		asynchat.async_chat.__init__(self, conn)

		indigo.activePlugin.debugLog(u'SMTPChannel __init__')

		self.__server = server
		self.__conn = conn
		self.__addr = addr
		self.__line = []
		self.__state = self.COMMAND
		self.__greeting = 0
		self.__mailfrom = None
		self.__rcpttos = []
		self.__data = ''
		self.__fqdn = socket.getfqdn()
		try:
			self.__peer = conn.getpeername()
		except socket.error as err:
			indigo.activePlugin.debugLog(u'SMTPChannel socket error')
			# a race condition	may occur if the other end is closing
			# before we can get the peername
			self.close()
			if err.args[0] != errno.ENOTCONN:
				raise
			return
		indigo.activePlugin.debugLog(u'SMTPChannel 220 %s %s' % (self.__fqdn, __version__))
		self.push('220 %s %s' % (self.__fqdn, __version__))
		self.set_terminator('\r\n')

	# Overrides base class for convenience
	def push(self, msg):
		indigo.activePlugin.debugLog(u'SMTPChannel push: %s' % msg)
		asynchat.async_chat.push(self, msg + '\r\n')

	# Implementation of base class abstract method
	def collect_incoming_data(self, data):
		indigo.activePlugin.debugLog(u'SMTPChannel collect: %s' % data)
		self.__line.append(data)

	# Implementation of base class abstract method
	def found_terminator(self):
		indigo.activePlugin.debugLog(u'SMTPChannel found_terminator')
		line = EMPTYSTRING.join(self.__line)
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
				self.push('502 Error: command "%s" not implemented' % command)
				return
			method(arg)
			return
		else:
			if self.__state != self.DATA:
				self.push('451 Internal confusion')
				return
			# Remove extraneous carriage returns and de-transparency according
			# to RFC 821, Section 4.5.2.
			data = []
			for text in line.split('\r\n'):
				if text and text[0] == '.':
					data.append(text[1:])
				else:
					data.append(text)
			self.__data = NEWLINE.join(data)
			status = self.__server.process_message(self.__peer,
												   self.__mailfrom,
												   self.__rcpttos,
												   self.__data)
			self.__rcpttos = []
			self.__mailfrom = None
			self.__state = self.COMMAND
			self.set_terminator('\r\n')
			if not status:
				self.push('250 Ok')
			else:
				self.push(status)

	# SMTP and ESMTP commands
	def smtp_HELO(self, arg):
		if not arg:
			self.push('501 Syntax: HELO hostname')
			return
		if self.__greeting:
			self.push('503 Duplicate HELO/EHLO')
		else:
			self.__greeting = arg
			self.push('250 %s' % self.__fqdn)

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
	
class SMTPServer(asyncore.dispatcher):
	
	def __init__(self, localaddr):
		self._localaddr = localaddr
		indigo.activePlugin.debugLog(u'SMTPServer __init__: %s' % str(localaddr))

		asyncore.dispatcher.__init__(self)
		try:
			self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
			# try to re-use a server port if possible
			self.set_reuse_addr()
			self.bind(localaddr)
			self.listen(5)
		except:
			# cleanup asyncore.socket_map before raising
			self.close()
			raise
		indigo.activePlugin.debugLog(u'SMTPServer listening')


	def __del__(self, device):
		indigo.activePlugin.debugLog(u'SMTPServer closing')
		self.close()

	def handle_read(self):
		indigo.activePlugin.debugLog(u'SMTPServer handle_read')

	def handle_write(self):
		indigo.activePlugin.debugLog(u'SMTPServer handle_write')

	def handle_connect(self):
		indigo.activePlugin.debugLog(u'SMTPServer handle_connect')

	def handle_close(self):
		indigo.activePlugin.debugLog(u'SMTPServer handle_close')

	def handle_error(self):
		indigo.activePlugin.debugLog(u'SMTPServer handle_error')

	def handle_accept(self):
		indigo.activePlugin.debugLog(u'SMTPServer handle_accept')
		try:
			conn, addr = self.accept()
		except TypeError:
			# sometimes accept() might return None
			return
		except socket.error as err:
			# ECONNABORTED might be thrown
			if err.args[0] != errno.ECONNABORTED:
				raise
			return
		else:
			# sometimes addr == None instead of (ip, port)
			if addr == None:
				return
		channel = SMTPChannel(self, conn, addr)

	def process_message(self, peer, mailfrom, rcpttos, data):
		indigo.activePlugin.debugLog(u'Receiving message from:' + peer)
		indigo.activePlugin.debugLog(u'Message addressed from:' + mailfrom)
		indigo.activePlugin.debugLog(u'Message addressed to	 :' + rcpttos)
		indigo.activePlugin.debugLog(u'Message length		 :' + str(len(data)))
		return



################################################################################
class Plugin(indigo.PluginBase):
					
	########################################
	# Main Plugin methods
	########################################
	def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
		indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
		
		self.debug = self.pluginPrefs.get(u"showDebugInfo", False)
		self.debugLog(u"Debugging enabled")

	def startup(self):
		indigo.server.log(u"Starting SMTPd")
		
		self.triggers = { }
		self.sck_map = {}

		self.updater = GitHubPluginUpdater(self)
		self.updateFrequency = float(self.pluginPrefs.get('updateFrequency', '24')) * 60.0 * 60.0
		self.next_update_check = time.time()


		port = int(self.pluginPrefs.get('smtpPort', '2525'))
		self.smtpServer = SMTPServer(('0.0.0.0', port))
							
	def shutdown(self):
		indigo.server.log(u"Shutting down SMTPd")
		self.smtpServer.close()
		

	def runConcurrentThread(self):
		
		try:
			while True:
				
				if self.updateFrequency > 0:
					if time.time() > self.next_update_check:
						self.updater.checkForUpdate()
						self.next_update_check = time.time() + self.updateFrequency

#				asyncore.loop(timeout=1, count=1)
				asyncore.loop()
				self.sleep(0.1)
								
		except self.stopThread:
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
		
	def triggerCheck(self, device):
		for triggerId, trigger in sorted(self.triggers.iteritems()):
			self.debugLog("\tChecking Trigger %s (%s), Type: %s" % (trigger.name, trigger.id, trigger.pluginTypeId))
			
	
	####################
	def validatePrefsConfigUi(self, valuesDict):
		self.debugLog(u"validatePrefsConfigUi called")
		errorDict = indigo.Dict()

		updateFrequency = int(valuesDict['updateFrequency'])
		if (updateFrequency < 0) or (updateFrequency > 24):
			errorDict['updateFrequency'] = u"Update frequency is invalid - enter a valid number (between 0 and 24)"

		smtpPort = int(valuesDict['smtpPort'])
		if smtpPort < 1024:
			errorDict['smtpPort'] = u"SMTP Port Number invalid"

		if len(errorDict) > 0:
			return (False, valuesDict, errorDict)
		return (True, valuesDict)

	########################################
	def closedPrefsConfigUi(self, valuesDict, userCancelled):
		if not userCancelled:
			self.debug = valuesDict.get("showDebugInfo", False)
			if self.debug:
				self.debugLog(u"Debug logging enabled")
			else:
				self.debugLog(u"Debug logging disabled")


	########################################
	# Menu Methods
	########################################

	def toggleDebugging(self):
		self.debug = not self.debug
		self.pluginPrefs["debugEnabled"] = self.debug
		indigo.server.log("Debug set to: " + str(self.debug))
		
	def checkForUpdates(self):
		self.updater.checkForUpdate()

	def updatePlugin(self):
		self.updater.update()

	def forceUpdate(self):
		self.updater.update(currentVersion='0.0.0')

