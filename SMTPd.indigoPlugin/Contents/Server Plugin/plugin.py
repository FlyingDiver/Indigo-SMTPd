#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import indigo  # noqa
import logging

import asyncio
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword

from email import message_from_string
from email.header import decode_header

########################################

def updateVar(name, value, folder):
    if name not in indigo.variables:
        indigo.variable.create(name, value=value, folder=folder)
    else:
        indigo.variable.updateValue(name, value)

class Authenticator:
    def __init__(self, username=None, password=None):
        self.logger = logging.getLogger("Plugin.Authenticator")
        self.username = username.encode("utf-8")
        self.password = password.encode("utf-8")

    def __call__(self, server, session, envelope, mechanism, auth_data):
        fail_nothandled = AuthResult(success=False, handled=False)
        if mechanism not in ("LOGIN", "PLAIN"):
            return fail_nothandled
        if not isinstance(auth_data, LoginPassword):
            return fail_nothandled
        if auth_data.login  != self.username or auth_data.password  != self.password:
            return fail_nothandled
        return AuthResult(success=True)

class Handler:
    def __init__(self):
        self.logger = logging.getLogger("Plugin.Handler")

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        envelope.rcpt_tos.append(address)
        return '250 OK'

    async def handle_DATA(self, server, session, envelope):

        message = message_from_string(envelope.content)

        bytes, encoding = decode_header(message.get("To"))[0]
        messageTo = bytes.decode(encoding) if encoding else message.get("To")

        bytes, encoding = decode_header(message.get("From"))[0]
        messageFrom = bytes.decode(encoding) if encoding else message.get("From")

        bytes, encoding = decode_header(message.get("Subject"))[0]
        messageSubject = bytes.decode(encoding) if encoding else message.get("Subject")

        if message.is_multipart():
            part0 = message.get_payload(0)      # we only look at the first alternative content part
            charset = part0.get_content_charset()
            messageText = part0.get_payload(decode=True).decode(charset) if charset else part0.get_payload()
        else:
            charset = message.get_content_charset()
            messageText = message.get_payload(decode=True).decode(charset) if charset else message.get_payload()

        self.logger.debug(f"Received Message To: {messageTo}")
        self.logger.debug(f"Received Message From: {messageFrom}")
        self.logger.debug(f"Received Message Subject: {messageSubject}")
        self.logger.debug(f"Received Message Text: {messageText}")

        updateVar("smtpd_messageTo",      messageTo,      indigo.activePlugin.pluginPrefs["folderId"])
        updateVar("smtpd_messageFrom",    messageFrom,    indigo.activePlugin.pluginPrefs["folderId"])
        updateVar("smtpd_messageSubject", messageSubject, indigo.activePlugin.pluginPrefs["folderId"])
        updateVar("smtpd_messageText",    messageText,    indigo.activePlugin.pluginPrefs["folderId"])

        return '250 OK'


################################################################################

class Plugin(indigo.PluginBase):

    ########################################
    # Main Plugin methods
    ########################################
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(msg)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(pfmt)
        self.logLevel = int(pluginPrefs.get(u"logLevel", logging.INFO))
        self.indigo_log_handler.setLevel(self.logLevel)
        self.logger.debug(f"logLevel = {self.logLevel}")

        self.triggers = []
        self.controller = None

    def startup(self):
        indigo.server.log("Starting SMTPd")

        if "SMTPd" in indigo.variables.folders:
            myFolder = indigo.variables.folders["SMTPd"]
        else:
            myFolder = indigo.variables.folder.create("SMTPd")
        self.pluginPrefs["folderId"] = myFolder.id

        port = int(self.pluginPrefs.get('smtpPort', '2525'))
        username = self.pluginPrefs.get('smtpUser', 'guest')
        password = self.pluginPrefs.get('smtpPassword', 'password')

        self.controller = Controller(
            Handler(),
            hostname='',
            port=port,
            authenticator=Authenticator(username, password),
            auth_require_tls=False,
            decode_data=True
        )
        self.controller.start()

    def shutdown(self):
        indigo.server.log("Shutting down SMTPd")
        self.controller.stop()

    ####################

    def triggerStartProcessing(self, trigger):
        self.logger.debug(f"Adding Trigger {trigger.name} ({trigger.id:d}) - {trigger.pluginTypeId}")
        assert trigger.id not in self.triggers
        self.triggers.append(trigger.id)

    def triggerStopProcessing(self, trigger):
        self.logger.debug(f"Removing Trigger {trigger.name} ({trigger.id:d})")
        assert trigger.id in self.triggers
        self.triggers.remove(trigger.id)

    def triggerCheck(self):
        for triggerId in self.triggers:
            trigger = indigo.triggers[triggerId]
            self.logger.debug(f"Checking Trigger {trigger.name} ({trigger.id}), Type: {trigger.pluginTypeId}")
            if trigger.pluginTypeId == 'messageReceived':
                indigo.trigger.execute(trigger)

    ####################
    def validatePrefsConfigUi(self, valuesDict):
        errorDict = indigo.Dict()

        smtpPort = int(valuesDict['smtpPort'])
        if smtpPort < 1024:
            errorDict['smtpPort'] = "SMTP Port Number invalid"

        if len(errorDict) > 0:
            return False, valuesDict, errorDict
        return True, valuesDict

    ########################################
    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            self.logLevel = int(valuesDict.get("logLevel", logging.INFO))
            self.indigo_log_handler.setLevel(self.logLevel)
            self.logger.debug(f"logLevel = {self.logLevel}")

