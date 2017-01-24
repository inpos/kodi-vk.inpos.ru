import sys, os, vk, time
from math import ceil
import xbmc, xbmcplugin, xbmcaddon, xbmcgui
import urlparse
from urllib3 import request
from urllib import urlencode

_ADDON_NAME =   'kodi-vk.inpos.ru'
_addon      =   xbmcaddon.Addon(id = _ADDON_NAME)
_addon_id   =   int(sys.argv[1])
_addon_url  =   sys.argv[0]
_addon_path =   _addon.getAddonInfo('path').decode('utf-8')

_APP_ID = '4353740'
_SCOPE  = 'friends,\
photos,audio,video,docs,notes,pages,status,wall,groups,messages,notifications,\
stats,'

DELAY = 1.0 / 3  # 3 запроса в секунду

# Служебные классы
class APIMethod(object):
    __slots__ = ['conn', '_method_name']

    def __init__(self, conn, method_name):
        self.conn = conn
        self._method_name = method_name
    def __getattr__(self, method_name):
        return APIMethod(self.conn, self._method_name + '.' + method_name)

    def __call__(self, **method_kwargs):
        return self.conn(self._method_name, **method_kwargs)

class Connection(object):
    def __init__(self, app_id, username = None, password = None, access_token = None, scope = ''):
        if access_token:
            session = vk.api.Session(access_token = access_token)
        else:
            session = vk.api.AuthSession(app_id, username, password, scope = scope)
        self.conn = vk.API(session)
        self.last_request = 0.0
    def __getattr__(self, method_name):
        return APIMethod(self, method_name)
    def __call__(self, method_name, **method_kwargs):
        # Ограничение 3 запроса в секунду
        delay = DELAY - (time.time() - self.last_request)
        if delay > 0:
            time.sleep(delay)
        res = self.conn(method_name, **method_kwargs)
        self.last_request = time.time()
        return res

class Group(object):
    def __init__(self, gid, conn):
        self.conn = conn
        self.gid = gid
        self.info = {'id': gid}

class User(object):
    '''Этот класс описывает свойства и методы пользователя.'''
    def __init__(self, uid, conn, get_info = True):
        self.conn = conn
        self.uid = uid
        if get_info:
            self.info = self.conn.users.get(user_id = uid, fields = 'uid,first_name,last_name,photo,photo_medium,online,last_seen')[0]
        else:
            self.info = {'id': uid}
    def friends(self, page_items = 20, index = 1, order = 'hints'):
        f =  self.conn.friends.get(user_id = self.uid,
                                   offset = ((page_items * index) - page_items),
                                   count=page_items,
                                   fields = 'uid,first_name,last_name,photo,photo_medium,online,last_seen',
                                   order = order)
        count = f['count']
        pages = ceil(count / page_items)
        l = []
        for i in f['items']:
            u = User(i['id'], self.conn, get_info = False)
            u.info = i
            l.append(u)
        return {'pages': pages, 'total': count, 'items': l}

    def groups(self):
        pass

class KodiVk:
    _token = 'vk_token'
    _username = 'vk_username'
    conn = None
    def __init__(self):
        self.paramstring = sys.argv[2]
        self.conn = self.__connect_()
        self.u = User(self.conn.users.get()[0]['uid'], self.conn)
    def _string(self, string_id):
        return _addon.getLocalizedString(string_id).encode('utf-8')
    @property
    def params(self):
        return dict(urlparse.parse_qsl(self.paramstring[1:]))
    def url(self, __dict_params=dict(), **parameters):
        __dict_params.update(parameters)
        return _addon_url + "?" + urlencode(__dict_params)
    def set_diritem(self, name, params, isFolder = False):
        if isFolder:
            url = self.url(**params)
            item = xbmcgui.ListItem(name)
            xbmcplugin.addDirectoryItem(_addon_id, url, item, isFolder = isFolder)
        else:
            url = params
            item = xbmcgui.ListItem(name)
            xbmcplugin.addDirectoryItem(_addon_id, url, item, isFolder = isFolder)
    def __connect_(self):
        token = _addon.getSetting(self._token)
        try:
            conn = Connection(access_token = token)
        except vk.api.VkAuthError:
            token = None
            count = 3
            while not token and count > 0:
                count -= 1
                login, password = self.__login_form_()
                try:
                    conn = Connection(_APP_ID, login, password, scope = _SCOPE)
                    token = conn._session.get_access_token()
                    _addon.setSetting(self._token, token)
                except vk.api.VkAuthError:
                    continue
        return conn
    def __login_form_(self):
        login_window = xbmc.Keyboard()
        login_window.setHeading(self._string(400500))
        login_window.setHiddenInput(False)
        login_window.setDefault(_addon.getSetting(self._username))
        login_window.doModal()
        if login_window.isConfirmed():
            username = login_window.getText()
            password_window = xbmc.Keyboard()
            password_window.setHeading(self._string(400500))
            password_window.setHiddenInput(True)
            password_window.doModal()
            if password_window.isConfirmed():
                return username, password_window.getText()
            else:
                raise Exception("Password input was cancelled.")
        else:
            raise Exception("Login input was cancelled.")
