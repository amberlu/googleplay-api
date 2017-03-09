#!/usr/bin/python

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import os
import io
import logging
import base64
import gzip
import requests

from google.protobuf import descriptor
from google.protobuf.internal.containers import RepeatedCompositeFieldContainer
from google.protobuf import text_format
from google.protobuf.message import Message, DecodeError

from googleplay_api import googleplay_pb2

class LoginError(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)

class RequestError(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)

config = None

class GooglePlayAPI(object):
    """Google Play Unofficial API Class

    Usual APIs methods are login(), search(), details(), bulkDetails(),
    download(), browse(), reviews() and list().

    toStr() can be used to pretty print the result (protobuf object) of the
    previous methods.

    toDict() converts the result into a dict, for easier introspection."""

    SERVICE = "androidmarket"
    URL_LOGIN = "https://android.clients.google.com/auth" # "https://www.google.com/accounts/ClientLogin"
    ACCOUNT_TYPE_GOOGLE = "GOOGLE"
    ACCOUNT_TYPE_HOSTED = "HOSTED"
    ACCOUNT_TYPE_HOSTED_OR_GOOGLE = "HOSTED_OR_GOOGLE"
    authSubToken = None
    # HTTP_PROXY = "http://81.137.100.158"

    USER_AGENT = 'Android-Finsky/6.8.44.F-all%20%5B0%5D%203087104 (api=3,versionCode=80684400,sdk=23,device=bullhead,hardware=bullhead,product=bullhead,platformVersionRelease=6.0.1,model=Nexus%205X,buildId=MHC19Q,isWideScreen=0)'
    DL_USER_AGENT = 'AndroidDownloadManager/6.0.1 (Linux; U; Android 6.0.1; Nexus 5X Build/MHC19Q)'

    def __init__(self, androidId=None, lang=None, debug=False): # you must use a device-associated androidId value
        self.preFetch = {}
        #if androidId == None:
        #    androidId = config.ANDROID_ID
        #if lang == None:
        #    lang = config.LANG
        self.androidId = androidId
        self.lang = lang
        self.debug = debug
        # self.proxy_dict = {
        #         "http"  : "http://81.137.100.158:8080",
        #         "https" : "http://81.137.100.158:8080",
        #         "ftp"   : "http://81.137.100.158:8080"
        #         }

    @staticmethod
    def read_config(config_file="config.py"):
        """
        Read the repository config

        The config is read from config_file, which is in the current directory.
        """
        global config

        if config is not None:
            return config
        if not os.path.isfile(config_file):
            logging.critical("Missing config file.")
            sys.exit(2)

        config = dict()

        logging.debug("Reading %s" % config_file)
        with io.open(config_file, "rb") as f:
            code = compile(f.read(), "config.py", "exec")
            exec(code, None, config)

        return config

    def toDict(self, protoObj):
        """Converts the (protobuf) result from an API call into a dict, for
        easier introspection."""
        iterable = False
        if isinstance(protoObj, RepeatedCompositeFieldContainer):
            iterable = True
        else:
            protoObj = [protoObj]
        retlist = []

        for po in protoObj:
            msg = dict()
            for fielddesc, value in po.ListFields():
                #print value, type(value), getattr(value, "__iter__", False)
                if fielddesc.type == descriptor.FieldDescriptor.TYPE_GROUP or isinstance(value, RepeatedCompositeFieldContainer) or isinstance(value, Message):
                    msg[fielddesc.name] = self.toDict(value)
                else:
                    msg[fielddesc.name] = value
            retlist.append(msg)
        if not iterable:
            if len(retlist) > 0:
                return retlist[0]
            else:
                return None
        return retlist

    def toStr(self, protoObj):
        """Used for pretty printing a result from the API."""
        return text_format.MessageToString(protoObj)

    def _try_register_preFetch(self, protoObj):
        fields = [i.name for (i,_) in protoObj.ListFields()]
        if ("preFetch" in fields):
            for p in protoObj.preFetch:
                self.preFetch[p.url] = p.response

    def setAuthSubToken(self, authSubToken):
        self.authSubToken = authSubToken

        # put your auth token in config.py to avoid multiple logins
        if self.debug:
            print("authSubToken: %s" % authSubToken)

    def login(self, email=None, password=None, authSubToken=None, proxy=None):
        """Login to your Google Account. You must provide either:
        - an email and password
        - a valid Google authSubToken"""
        if (authSubToken is not None):
            self.setAuthSubToken(authSubToken)
            self.proxy_dict = proxy
            # TODO: not really implemented yet
        else:
            if (email is None or password is None):
                raise Exception("You should provide at least authSubToken or (email and password)")
            params = {"Email": email,
                                "Passwd": password,
                                "service": self.SERVICE,
                                "accountType": self.ACCOUNT_TYPE_HOSTED_OR_GOOGLE,
                                "has_permission": "1",
                                "source": "android",
                                "androidId": self.androidId,
                                "app": "com.android.vending",
                                #"client_sig": self.client_sig,
                                "device_country": "us",
                                "operatorCountry": "us",
                                "lang": "us",
                                "sdk_version": "22"}
            headers = {
                "Accept-Encoding": "",
            }
            self.proxy_dict = proxy
            response = requests.post(self.URL_LOGIN, data=params, headers=headers, proxies=proxy, verify=True)
            data = response.text.split()
            params = {}
            for d in data:
                if not "=" in d: continue
                k, v = d.split("=")
                params[k.strip().lower()] = v.strip()
            if "auth" in params:
                #print("Auth-Token found: %s" % params["auth"])
                self.setAuthSubToken(params["auth"])
            elif "error" in params:
                raise LoginError("server says: " + params["error"])
            else:
                raise LoginError("Auth token not found.")

    def executeRequestApi2(self, path, datapost=None, post_content_type="application/x-www-form-urlencoded; charset=UTF-8"):
        if (datapost is None and path in self.preFetch):
            data = self.preFetch[path]
        else:
            headers = { "Accept-Language": self.lang,
                                    "Authorization": "GoogleLogin auth=%s" % self.authSubToken,
                                    "X-DFE-Enabled-Experiments": "cl:billing.select_add_instrument_by_default",
                                    "X-DFE-Unsupported-Experiments": "nocache:billing.use_charging_poller,market_emails,buyer_currency,prod_baseline,checkin.set_asset_paid_app_field,shekel_test,content_ratings,buyer_currency_in_app,nocache:encrypted_apk,recent_changes",
                                    "X-DFE-Device-Id": self.androidId,
                                    "X-DFE-Client-Id": "am-android-google",
                                    "User-Agent": self.USER_AGENT,
                                    "X-DFE-SmallestScreenWidthDp": "335",
                                    "X-DFE-Filter-Level": "3",
                                    "Accept-Encoding": "",
                                    "Host": "android.clients.google.com"}

            if datapost is not None:
                headers["Content-Type"] = post_content_type

            url = "https://android.clients.google.com/fdfe/%s" % path
            if datapost is not None:
                response = requests.post(url, data=datapost, headers=headers, proxies=self.proxy_dict, verify=True)
            else:
                response = requests.get(url, headers=headers, proxies=self.proxy_dict, verify=True)
            data = response.content
            #print(data)
        '''
        data = StringIO.StringIO(data)
        gzipper = gzip.GzipFile(fileobj=data)
        data = gzipper.read()
        '''
        message = googleplay_pb2.ResponseWrapper.FromString(data)
        self._try_register_preFetch(message)

        # Debug
        #print text_format.MessageToString(message)
        return message

    #####################################
    # Google Play API Methods
    #####################################

    def search(self, query, nb_results=None, offset=None):
        """Search for apps."""
        path = "search?c=3&q=%s" % requests.utils.quote(query) # TODO handle categories
        if (nb_results is not None):
            path += "&n=%d" % int(nb_results)
        if (offset is not None):
            path += "&o=%d" % int(offset)

        message = self.executeRequestApi2(path)
        return message.payload.searchResponse

    def details(self, packageName):
        """Get app details from a package name.
        packageName is the app unique ID (usually starting with 'com.')."""
        path = "details?doc=%s" % requests.utils.quote(packageName)
        message = self.executeRequestApi2(path)
        return message.payload.detailsResponse

    def bulkDetails(self, packageNames):
        """Get several apps details from a list of package names.

        This is much more efficient than calling N times details() since it
        requires only one request.

        packageNames is a list of app ID (usually starting with 'com.')."""
        path = "bulkDetails"
        req = googleplay_pb2.BulkDetailsRequest()
        req.docid.extend(packageNames)
        data = req.SerializeToString()
        message = self.executeRequestApi2(path, data, "application/x-protobuf")
        return message.payload.bulkDetailsResponse

    def browse(self, cat=None, ctr=None):
        """Browse categories.
        cat (category ID) and ctr (subcategory ID) are used as filters."""
        path = "browse?c=3"
        if (cat != None):
            path += "&cat=%s" % requests.utils.quote(cat)
        if (ctr != None):
            path += "&ctr=%s" % requests.utils.quote(ctr)
        message = self.executeRequestApi2(path)
        return message.payload.browseResponse

    def list(self, cat, ctr=None, nb_results=None, offset=None):
        """List apps.

        If ctr (subcategory ID) is None, returns a list of valid subcategories.

        If ctr is provided, list apps within this subcategory."""
        path = "list?c=3&cat=%s" % requests.utils.quote(cat)
        if (ctr != None):
            path += "&ctr=%s" % requests.utils.quote(ctr)
        if (nb_results != None):
            path += "&n=%s" % requests.utils.quote(nb_results)
        if (offset != None):
            path += "&o=%s" % requests.utils.quote(offset)
        message = self.executeRequestApi2(path)
        return message.payload.listResponse

    def reviews(self, packageName, filterByDevice=False, sort=2, nb_results=None, offset=None):
        """Browse reviews.
        packageName is the app unique ID.
        If filterByDevice is True, return only reviews for your device."""
        path = "rev?doc=%s&sort=%d" % (requests.utils.quote(packageName), sort)
        if (nb_results is not None):
            path += "&n=%d" % int(nb_results)
        if (offset is not None):
            path += "&o=%d" % int(offset)
        if(filterByDevice):
            path += "&dfil=1"
        message = self.executeRequestApi2(path)
        return message.payload.reviewResponse

    def download(self, packageName, versionCode, offerType=1):
        """Download an app and return its raw data (APK file).

        packageName is the app unique ID (usually starting with 'com.').

        versionCode can be grabbed by using the details() method on the given
        app."""
        path = "purchase"
        data = "ot=%d&doc=%s&vc=%d" % (offerType, packageName, versionCode)
        message = self.executeRequestApi2(path, data)

        url = message.payload.buyResponse.purchaseStatusResponse.appDeliveryData.downloadUrl
        #print(message)
        #print(message.payload)
        cookie = message.payload.buyResponse.purchaseStatusResponse.appDeliveryData.downloadAuthCookie[0]

        cookies = {
            str(cookie.name): str(cookie.value) # python-requests #459 fixes this
        }

        headers = {
                   "User-Agent" : self.DL_USER_AGENT,
                   "Accept-Encoding": "",
                  }

        response = requests.get(url, headers=headers, cookies=cookies, proxies=self.proxy_dict, verify=True)
        return response.content

