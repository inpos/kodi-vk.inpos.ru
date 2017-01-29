# -*- coding: utf-8 -*-
import sys, os, vk, time
from math import ceil
import xbmc, xbmcplugin, xbmcaddon, xbmcgui
import urlparse
import urllib2
from urllib import urlencode
import re

_VERSION = '0.0.1'

_ADDON_NAME =   'kodi-vk.inpos.ru'
_addon      =   xbmcaddon.Addon(id = _ADDON_NAME)
_addon_id   =   int(sys.argv[1])
_addon_url  =   sys.argv[0]
_addon_path =   _addon.getAddonInfo('path').decode('utf-8')

_APP_ID = '4353740'
_SCOPE  = 'friends,photos,audio,video,groups,messages,offline'
_SETTINGS_TOKEN = 'vk_token'
_USERNAME = 'vk_username'
_LOGIN_RETRY = 3
_VK_API_VERSION = '5.62'

_PHOTO_THUMB_KEY = 'photo_130'

_CTYPE_VIDEO = 'video'
_CTYPE_AUDIO = 'audio'
_CTYPE_IMAGE = 'image'

_DO_HOME = 'home'
_DO_MY_VIDEO = 'my_video'
_DO_ALL_VIDEO = 'all_video'
_DO_PLAY_VIDEO = 'play_video'
_DO_MY_AUDIO = 'my_audio'
_DO_MY_PHOTO = 'my_photo'
_DO_ALL_PHOTO = 'all_photo'
_DO_FRIENDS = 'friends'
_DO_GROUPS = 'groups'

_VK_VIDEO_SOURCE = 'vk_video'
_YOUTUBE_VIDEO_SOURCE = 'youtube_video'
_UNKNOWN_VIDEO_SOURCE = 'unknown_video'

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
    '''Соединяемся с сайтом'''
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
        if 'v' not in method_kwargs: method_kwargs['v'] = _VK_API_VERSION
        res = self.conn(method_name, **method_kwargs)
        self.last_request = time.time()
        return res

class Group(object):
    '''Группа'''
    def __init__(self, gid, conn):
        self.conn = conn
        self.id = gid
        self.info = {}
    @property
    def counters(self):
        return self.conn.groups.getById(group_id = self.id, fields = 'counters')
    def videos(self, page_items = 20, page = 1, album = None):
        return media_entries('video', self.conn, -self.id, page_items, page, album)

def media_entries(e_type, conn, oid, page_items = 20, page = 1, album = None):
    if album:
        entries = getattr(conn, e_type).get(owner_id = oid,
                          offset = ((page_items * page) - page_items),
                          count = page_items,
                          album_id = album)
    else:
        entries = getattr(conn, e_type).get(owner_id = oid,
                          offset = ((page_items * page) - page_items),
                          count = page_items)
    count = entries['count']
    pages = int(ceil(count / float(page_items)))
    l = []
    for i in entries['items']:
        entry_id = str(i['owner_id']) + '_' + str(i['id'])
        e = Entry(e_type, entry_id, conn)
        e.info = i
        l.append(e)
    return {'pages': pages, 'total': count, 'items': l}

class Entry(object):
    def __init__(self, e_type, eid, conn):
        self.type = e_type
        self.id = eid
        self.conn = conn
        self.info = {}
    def set_info(self):
        if self.type == 'video':
            self.info = self.conn.video.get(videos = self.id)['items'][0]
        elif self.type == 'audio':
            self.info = self.conn.audio.getById(audios = self.id)['items'][0]
        elif self.type == 'photos':
            self.info = self.conn.photos.getById(photos = self.id)['items'][0]

class User(object):
    '''Этот класс описывает свойства и методы пользователя.'''
    def __init__(self, uid, conn):
        self.conn = conn
        self.id = uid
        self.info = {}
    def friends(self, page_items = 20, page = 1, order = 'hints'):
        f =  self.conn.friends.get(user_id = self.id,
                                   offset = ((page_items * page) - page_items),
                                   count = page_items,
                                   fields = 'first_name,last_name,photo_50,photo_100,photo_200',
                                   order = order)
        count = f['count']
        pages = ceil(count / page_items)
        l = []
        for i in f['items']:
            u = User(i['id'], self.conn)
            u.info = i
            l.append(u)
        return {'pages': pages, 'total': count, 'items': l}

    def groups(self, page_items = 20, page = 1):
        gr = self.conn.groups.get(user_id = self.id,
                                 offset = ((page_items * page) - page_items),
                                 count = page_items,
                                 fields = 'name,description,is_closed,deactivated,is_member,photo_50,photo_100,photo_200,age_limits',
                                 extended = 1)
        count = gr['count']
        pages = ceil(count / page_items)
        l = []
        for i in gr['items']:
            if i['is_closed'] > 0 and i['is_member'] == 0: continue
            g = Group(i['id'], self.conn)
            g.info = i
            l.append(g)
        return {'pages': pages, 'total': count, 'items': l}
    def videos(self, page_items = 20, page = 1, album = None):
        return media_entries('video', self.conn, self.id, page_items, page, album)

class KodiVKGUIPhotos(object):
    def __init__(self, root):
        self.root = root
    def _my_photo(self):
        self.root.add_folder(self.root.gui._string(400508), {'do': _DO_ALL_PHOTO, 'oid': self.root.u.id, 'page': 1})
        xbmcplugin.endOfDirectory(_addon_id)

class KodiVKGUIVideos(object):
    def __init__(self, root):
        self.root = root
    def __get_video_source_(self, v):
        is_vk_url_re = re.compile('https?\:\/\/[^\/]*vk.com\/.*')
        is_youtube_url_re = re.compile('https\:\/\/www.youtube.com\/.*')
        player_url = v.info['player']
        if len(is_vk_url_re.findall(player_url)) > 0: return _VK_VIDEO_SOURCE
        if len(is_youtube_url_re.findall(player_url)) > 0: return _YOUTUBE_VIDEO_SOURCE
        return _UNKNOWN_VIDEO_SOURCE
        
    def _my_video(self):
        self.root.add_folder(self.root.gui._string(400509), {'do': _DO_ALL_VIDEO, 'oid': self.root.u.id, 'page': 1})
        xbmcplugin.endOfDirectory(_addon_id)
    def _all_video(self):
        page = int(self.root.params['page'])
        oid = self.root.params['oid']
        if page > 1:
            self.root.add_folder(self.root.gui._string(400601), {'do': _DO_ALL_VIDEO, 'oid': self.root.u.id, 'page': page - 1})
        vids = media_entries('video', self.root.conn, oid, page = page)
        for v in vids['items']:
            list_item = xbmcgui.ListItem(v.info['title'])
            list_item.setInfo('video', {
                                        'title'     : v.info['title'],
                                        'duration'  : int(v.info['duration']),
                                        'plot'      : v.info['description']
                                        }
                              )
            list_item.setArt({'thumb': v.info['photo_130'], 'icon': v.info['photo_130'], 'fanart': v.info['photo_130']})
            list_item.setProperty('IsPlayable', 'true')
            v_source = self.__get_video_source_(v)
            if v_source == _VK_VIDEO_SOURCE:
                params = {'do': _DO_PLAY_VIDEO, 'vid': v.id}
                url = self.root.url(**params)
                xbmcplugin.addDirectoryItem(_addon_id, url, list_item, isFolder = False)
            else:
                continue
        if page < vids['pages']:
            self.root.add_folder(self.root.gui._string(400602), {'do': _DO_ALL_VIDEO, 'oid': self.root.u.id, 'page': page + 1})
        xbmcplugin.endOfDirectory(_addon_id)
    def _play_video(self):
        vid = self.root.params['vid']
        v = Entry('video', vid, self.root.conn)
        v.set_info()
        if 'files' in v.info:
            paths = {}
            for k in v.info['files'].keys():
                paths[k.split('_')[1]] = v.info['files'][k]
        else:
            v_url = v.info['player']
            paths = self.root.parse_vk_player_html(v_url)
        ### Здесь должно браться разрешение из настроек
        k = max(paths.keys())
        play_item = xbmcgui.ListItem(path = paths[k])
        xbmcplugin.setResolvedUrl(_addon_id, True, listitem = play_item)

class KodiVkGUI:
    '''Окошки, диалоги, сообщения'''
    def __init__(self, root):
        self.root = root
        self.photos = KodiVKGUIPhotos(self.root)
        self.videos = KodiVKGUIVideos(self.root)
    def _string(self, string_id):
        return _addon.getLocalizedString(string_id).encode('utf-8')
    def _login_form(self):
        login_window = xbmc.Keyboard()
        login_window.setHeading(self._string(400500))
        login_window.setHiddenInput(False)
        login_window.setDefault(_addon.getSetting(_USERNAME))
        login_window.doModal()
        if login_window.isConfirmed():
            username = login_window.getText()
            password_window = xbmc.Keyboard()
            password_window.setHeading(self._string(400501))
            password_window.setHiddenInput(True)
            password_window.doModal()
            if password_window.isConfirmed():
                return username, password_window.getText()
            else:
                raise Exception("Password input was cancelled.")
        else:
            raise Exception("Login input was cancelled.")
    def _home(self):
        c_type = self.root.params.get('content_type', None)
        if not c_type:
            xbmc.log('No content_type')
            return
        if c_type == _CTYPE_VIDEO:
            self.root.add_folder(self._string(400502), {'do': _DO_MY_VIDEO})
        elif c_type == _CTYPE_AUDIO:
            self.root.add_folder(self._string(400503), {'do': _DO_MY_AUDIO})
        elif c_type == _CTYPE_IMAGE:
            self.root.add_folder(self._string(400504), {'do': _DO_MY_PHOTO})
        else:
            xbmc.log('Unknown content_type: %s' % (c_type,))
            return
        self.root.add_folder(self._string(400505), {'do': _DO_FRIENDS})
        self.root.add_folder(self._string(400506), {'do': _DO_GROUPS})
        xbmcplugin.endOfDirectory(_addon_id)
    
class KodiVk:
    conn = None
    def __init__(self):
        self.gui = KodiVkGUI(self)
        p = {'do': _DO_HOME}
        if sys.argv[2]:
            p.update(dict(urlparse.parse_qsl(sys.argv[2][1:])))
        self.params = p
        self.c_type = p.get('content_type', None)
        self.conn = self.__connect_()
        u_info = self.conn.users.get()[0]
        self.u = User(u_info['id'], self.conn)
        self.u.info = u_info
    def url(self, params=dict(), **kwparams):
        if self.c_type:
            kwparams['content_type'] = self.c_type
        params.update(kwparams)
        return _addon_url + "?" + urlencode(params)
    def add_folder(self, name, params):
        url = self.url(**params)
        item = xbmcgui.ListItem(name)
        xbmcplugin.addDirectoryItem(_addon_id, url, item, isFolder = True)
    def add_play_entry(self, name, url):
        item = xbmcgui.ListItem(name)
        xbmcplugin.addDirectoryItem(_addon_id, url, item, isFolder = False)
    def __connect_(self):
        token = _addon.getSetting(_SETTINGS_TOKEN)
        conn = Connection(_APP_ID, access_token = token)
        if not conn.conn._session.access_token:
            token = None
            count = _LOGIN_RETRY
            while not token and count > 0:
                count -= 1
                login, password = self.gui._login_form()
                try:
                    conn = Connection(_APP_ID, login, password, scope = _SCOPE)
                    token = conn.conn._session.access_token
                    _addon.setSetting(_SETTINGS_TOKEN, token)
                except vk.api.VkAuthError:
                    continue
        return conn
    def parse_vk_player_html(self, v_url):
        p = re.compile('"url(\d+)":"([^"]+)"')
        headers = {'User-Agent' : 'Kodi-vk/%s (linux gnu)' % (_VERSION,)}
        req = urllib2.Request(v_url, None, headers)
        http_res = urllib2.urlopen(req)
        if http_res.code != 200:
            return None
        html = http_res.read()
        re_res = p.findall(html)
        if len(re_res) < 1:
            return None
        res = {}
        for tup in re_res:
            res[tup[0]] = tup[1].replace('\\', '')
        return res

if __name__ == '__main__':
    kvk = KodiVk()
    
    _DO = {
       _DO_HOME: kvk.gui._home,
       _DO_MY_PHOTO: kvk.gui.photos._my_photo,
       _DO_MY_VIDEO: kvk.gui.videos._my_video,
       _DO_ALL_VIDEO: kvk.gui.videos._all_video,
       _DO_PLAY_VIDEO: kvk.gui.videos._play_video
       }
    
    _do_method = kvk.params['do']
    if _do_method in _DO.keys():
        _DO[_do_method]()
