import sys
from slc.mail2news.browser.mailhandler import MailHandler
from slc.zopescript.script import ConsoleScript


class MailHandlerScript(ConsoleScript):
    def run(self):
        mailString = sys.stdin.read()
        self.portal.REQUEST['Mail'] = mailString
        mailhandler_view = MailHandler(self.context, self.context.REQUEST)
        mailhandler_view()

mail_handler = MailHandlerScript()
