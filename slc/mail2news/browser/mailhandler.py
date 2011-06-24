from Acquisition import aq_inner, aq_parent, aq_base
from Products.Five import BrowserView
from Products.CMFDefault.NewsItem import NewsItem
from DateTime import DateTime
import logging
import StringIO, re, rfc822, mimetools, email, multifile
from Products.Archetypes.event import ObjectInitializedEvent
import zope.event
from Testing import makerequest
from plone.i18n.normalizer.interfaces import IUserPreferredURLNormalizer

log = logging.getLogger('slc.mail2news')

conf_dict = { 'keepdate': 0 }

# Simple return-Codes for web-callable-methods for the smtp2zope-gate
TRUE = "TRUE"
FALSE = "FALSE"

# mail-parameter in the smtp2http-request
MAIL_PARAMETER_NAME = "Mail"

class MailHandler(BrowserView):

    def __call__(self):
        """ Handles mail received in request
        """
        #TODO: add this, seems to make sense
        #if self.checkMail(self.request):
        #    return FALSE

        obj = self.addMail(self.getMailFromRequest(self.request))
        event = ObjectInitializedEvent(obj, self.request)
        zope.event.notify(event)

        msg = 'Created news item %s' % ('/'.join([self.context.absolute_url(), obj.getId()]))
        log.info(msg)
        return msg

    def addMail(self, mailString):
        """ Store mail as news item
            Returns created item
        """

        archive = self.context
        pw = self.context.portal_workflow
        
        (header, body) = splitMail(mailString)

        # if 'keepdate' is set, get date from mail,
        if self.getValueFor('keepdate'):
            timetuple = rfc822.parsedate_tz(header.get('date'))
            time = DateTime(rfc822.mktime_tz(timetuple))
        # ... take our own date, clients are always lying!
        else:
            time = DateTime()

        (TextBody, ContentType, HtmlBody, Attachments) = unpackMail(mailString)

        # Test Zeitangabe hinter Subject
        from datetime import date
        today = date.today()
        mydate = today.strftime("%d.%m.%Y")





        # let's create the news item

        subject = mime_decode_header(header.get('subject', 'No Subject'))
        sender = mime_decode_header(header.get('from','No From'))
        #title = "%s / %s" % (subject, sender)
        title = "%s"  % (subject)

        new_id = IUserPreferredURLNormalizer(self.request).normalize(title)
        id = self._findUniqueId(new_id)
        # ContentType is only set for the TextBody
        if ContentType:
            body = TextBody
        else:
            body = self.HtmlToText(HtmlBody)

# als vorlaeufige Loesung
        desc = "%s..." % (body[:60])
        uni_aktuell_body = "<p><strong>%s: %s</strong></p> <p>&nbsp;</p><pre>%s</pre>" % (mydate, sender, body)
#        uni_aktuell_body = '<p>&nbsp;</p>' + body

        objid = self.context.invokeFactory(NewsItem.meta_type, id=id, title=title, text=uni_aktuell_body, description=desc)

        mailObject = getattr(self.context, objid)
        try:
#original            pw.doActionFor(mailObject, 'hide')
            pw.doActionFor(mailObject, 'publish')
        except:
            pass
        return mailObject

    def _findUniqueId(self, id):
        """Find a unique id in the parent folder, based on the given id, by
        appending -n, where n is a number between 1 and the constant
        RENAME_AFTER_CREATION_ATTEMPTS, set in config.py. If no id can be
        found, return None.
        """
        from Products.Archetypes.config import RENAME_AFTER_CREATION_ATTEMPTS
        parent = aq_parent(aq_inner(self))
        parent_ids = parent.objectIds()
        check_id = lambda id, required: id in parent_ids

        invalid_id = check_id(id, required=1)
        if not invalid_id:
            return id

        idx = 1
        while idx <= RENAME_AFTER_CREATION_ATTEMPTS:
            new_id = "%s-%d" % (id, idx)
            if not check_id(new_id, required=1):
                return new_id
            idx += 1

        return None


    def getMailFromRequest(self, REQUEST):
        # returns the Mail from the REQUEST-object as string

        return str(REQUEST[MAIL_PARAMETER_NAME])


    def getValueFor(self, key):
        return conf_dict[key]


def splitMail(mailString):
    """ returns (header,body) of a mail given as string 
    """
    msg = mimetools.Message(StringIO.StringIO(str(mailString)))

    # Get headers
    mailHeader = {}
    for (key,value) in msg.items():
        mailHeader[key] = value
        
    # Get body
    msg.rewindbody()
    mailBody = msg.fp.read()

    return (mailHeader, mailBody)

def unpackMail(mailString):
    """ returns body, content-type, html-body and attachments for mail-string.
    """    
    return unpackMultifile(multifile.MultiFile(StringIO.StringIO(mailString)))

def unpackMultifile(multifile, attachments=None):
    """ Unpack multifile into plainbody, content-type, htmlbody and attachments.
    """
    if attachments is None:
        attachments=[]
    textBody = htmlBody = contentType = ''

    msg = mimetools.Message(multifile)
    maintype = msg.getmaintype()
    subtype = msg.getsubtype()

    name = msg.getparam('name')

    if not name:
        # Check for disposition header (RFC:1806)
        disposition = msg.getheader('Content-Disposition')
        if disposition:
            matchObj = re.search('(?i)filename="*(?P<filename>[^\s"]*)"*',
                                   disposition)
            if matchObj:
                name = matchObj.group('filename')

    # Recurse over all nested multiparts
    if maintype == 'multipart':
        multifile.push(msg.getparam('boundary'))
        multifile.readlines()
        while not multifile.last:
            multifile.next()

            (tmpTextBody, tmpContentType, tmpHtmlBody, tmpAttachments) = \
                                       unpackMultifile(multifile, attachments)

            # Return ContentType only for the plain-body of a mail
            if tmpContentType and not textBody:
                textBody = tmpTextBody
                contentType = tmpContentType

            if tmpHtmlBody:
                htmlBody = tmpHtmlBody
        
            if tmpAttachments:
                attachments = tmpAttachments

        multifile.pop()
        return (textBody, contentType, htmlBody, attachments)

    # Process MIME-encoded data
    plainfile = StringIO.StringIO()

    try:
        mimetools.decode(multifile,plainfile,msg.getencoding())
    # unknown or no encoding? 7bit, 8bit or whatever... copy literal
    except ValueError:
        mimetools.copyliteral(multifile,plainfile)

    body = plainfile.getvalue()
    plainfile.close()

    # Get plain text
    if maintype == 'text' and subtype == 'plain' and not name:
        textBody = body
        contentType = msg.get('content-type', 'text/plain')
    else:
        # No name? This should be the html-body...
        if not name:
            name = '%s.%s' % (maintype,subtype)
            htmlBody = body
        
        attachments.append({'filename' : mime_decode_header(name), 
                            'filebody' : body,
                            'maintype' : maintype,
                            'subtype' : subtype})
            
    return (textBody, contentType, htmlBody, attachments)

def mime_decode_header(header):
    """ Returns the unfolded and undecoded header
    """
    # unfold the header
    header = re.sub(r'\r?\n\s+',' ', header)
    
    # different naming between python 2.4 and 2.6?
    if hasattr(email, 'header'):
        header = email.header.decode_header(header)
    else:
        header = email.Header.decode_header(header)
        
    headerout = []
    for line in header:
        if line[1]:
            line = line[0].decode(line[1])
        else:
            line = line[0]
        headerout.append(line)
    return '\n'.join(headerout)

