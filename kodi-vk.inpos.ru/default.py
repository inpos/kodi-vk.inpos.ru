# -*- coding: utf-8 -*-
import sys, vk, time
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
_SETTINGS_PAGE_ITEMS = 20

_USERNAME = 'vk_username'
_LOGIN_RETRY = 3
_VK_API_VERSION = '5.62'

_PHOTO_THUMB_KEY = 'photo_130'

_CTYPE_VIDEO = 'video'
_CTYPE_AUDIO = 'audio'
_CTYPE_IMAGE = 'image'

_DO_HOME = 'home'
_DO_MAIN_VIDEO = 'main_video'
_DO_VIDEO = 'video'
_DO_VIDEO_ALBUMS = 'video_albums'
_DO_PLAY_VIDEO = 'play_video'
_DO_MAIN_AUDIO = 'main_audio'
_DO_MAIN_PHOTO = 'main_photo'
_DO_PHOTO = 'photo'
_DO_PHOTO_ALBUMS = 'photo_albums'
_DO_FRIENDS = 'friends'
_DO_GROUPS = 'groups'
_DO_MEMBERS = 'members'

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
    def set_info(self):
        self.info = self.conn.groups.getById(group_id = int(self.id) * -1)[0]
    def members(self, page_items = _SETTINGS_PAGE_ITEMS, page = 1):
        m = self.conn.groups.getMembers(group_id = self.id,
                                 offset = ((page_items * page) - page_items),
                                 fields = 'first_name,last_name,photo_50,photo_100,photo_200',
                                 count = page_items)
        count = m['count']
        pages = ceil(count / page_items)
        l = []
        for i in m['items']:
            member = User(i['id'], self.conn)
            member.info = i
            l.append(member)
        return {'pages': pages, 'total': count, 'items': l}

# Благодарю автора статьи https://habrahabr.ru/post/193374/
def switch_view():
    skin_used = xbmc.getSkinDir()
    if skin_used == 'skin.confluence':
        xbmc.executebuiltin('Container.SetViewMode(500)') # Вид "Эскизы".
    elif skin_used == 'skin.aeon.nox':
        xbmc.executebuiltin('Container.SetViewMode(512)') # Вид "Инфо-стена"


def media_entries(e_method, conn, oid, **kwargs):
    page_items = kwargs.pop('page_items', _SETTINGS_PAGE_ITEMS)
    page = kwargs.pop('page', 1)
    album = kwargs.pop('album', None)
    kwargs.update({
              'owner_id': oid,
              'offset': ((page_items * page) - page_items),
              'count': page_items
              })
    if album: kwargs['album_id'] = album
    try:
        entries = getattr(conn, e_method)(**kwargs)
    except vk.exceptions.VkAPIError, e:
        if e.code == 15 or (e.code >= 200 and e.code < 300):
            entries = {'count': 0, 'items': []}
        else:
            raise
    count = entries['count']
    pages = int(ceil(count / float(page_items)))
    l = []
    for i in entries['items']:
        if e_method.split('.')[-1] == 'getAlbums':
            entry_id = str(i['id'])
        else:
            entry_id = str(i['owner_id']) + '_' + str(i['id'])
        e = Entry(e_method, entry_id, conn)
        e.info = i
        l.append(e)
    return {'pages': pages, 'total': count, 'items': l}

class Entry(object):
    def __init__(self, e_method, eid, conn):
        self.method = e_method
        self.id = eid
        self.conn = conn
        self.info = {}
    def set_info(self):
        if self.method == 'video.get':
            self.info = self.conn.video.get(videos = self.id)['items'][0]
        elif self.method == 'audio.get':
            self.info = self.conn.audio.getById(audios = self.id)['items'][0]
        elif self.method == 'photos.get':
            self.info = self.conn.photos.getById(photos = self.id)['items'][0]

class User(object):
    '''Этот класс описывает свойства и методы пользователя.'''
    def __init__(self, uid, conn):
        self.conn = conn
        self.id = uid
        self.info = {}
    def set_info(self):
        self.info = self.conn.users.get(user_id = self.id, fields = 'first_name,last_name,photo_50,photo_100,photo_200')[0]
    def friends(self, page_items = _SETTINGS_PAGE_ITEMS, page = 1, order = 'hints'):
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

    def groups(self, page_items = _SETTINGS_PAGE_ITEMS, page = 1):
        gr = self.conn.groups.get(user_id = self.id,
                                 offset = ((page_items * page) - page_items),
                                 count = page_items,
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

class KodiVKGUIPhotos(object):
    def __init__(self, root):
        self.root = root
    def _main_photo(self):
        oid = self.root.params['oid']
        self.root.add_folder(self.root.gui._string(400508), {'do': _DO_PHOTO, 'oid': oid, 'page': 1})
        self.root.add_folder(self.root.gui._string(400511), {'do': _DO_PHOTO_ALBUMS, 'oid': oid, 'page': 1})
        xbmcplugin.endOfDirectory(_addon_id)
    def _photo_albums(self):
        page = int(self.root.params['page'])
        oid = self.root.params['oid']
        kwargs = {'page': page, 'need_covers': 1, 'need_system': 1}
        albums = media_entries('photos.getAlbums', self.root.conn, oid, **kwargs)
        if page < albums['pages']:
            params = {'do': _DO_PHOTO_ALBUMS,'oid': oid,'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        for a in albums['items']:
            list_item = xbmcgui.ListItem(a.info['title'])
            list_item.setInfo('pictures', {'title': a.info['title']})
            list_item.setArt({'thumb': a.info['thumb_src'], 'icon': a.info['thumb_src']})
            params = {'do': _DO_PHOTO, 'oid': oid, 'album': a.id, 'page': 1}
            url = self.root.url(**params)
            xbmcplugin.addDirectoryItem(_addon_id, url, list_item, isFolder = True)
        if page < albums['pages']:
            params = {'do': _DO_PHOTO_ALBUMS,'oid': oid,'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        xbmcplugin.endOfDirectory(_addon_id)
        switch_view()
    def _photo(self):
        page = int(self.root.params['page'])
        oid = self.root.params['oid']
        album = self.root.params.get('album', None)
        kwargs = {'page': page}
        if album:
            kwargs['album'] = album
            photos = media_entries('photos.get', self.root.conn, oid, **kwargs)
        else:
            photos = media_entries('photos.getAll', self.root.conn, oid, **kwargs)
        if page < photos['pages']:
            params = {'do': _DO_PHOTO,'oid': oid,'page': page + 1}
            if album: params['album'] = album
            self.root.add_folder(self.root.gui._string(400602), params)
        for index in range(len(photos['items'])):
            p = photos['items'][index]
            num = (_SETTINGS_PAGE_ITEMS * page) + index + 1
            list_item = xbmcgui.ListItem('%04d' % (num,))
            p_info = {
                        'title'     : '%04d' % (num,),
                        'tagline'      : p.info['text']
                        }
            if 'width' in p.info.keys(): p_info['exif:resolution'] = '%d,%d' % (p.info['width'], p.info['height'])
            list_item.setInfo('pictures', p_info)
            list_item.setArt({'thumb': p.info['photo_130'], 'icon': p.info['photo_75']})
            r = map(lambda x: int(x.split('_')[1]), filter(lambda x: x.startswith('photo_'), p.info.keys()))
            ### Здесь надо подумать над настройкой
            url_key = max(r)
            url = p.info['photo_%d' % (url_key,)]
            xbmcplugin.addDirectoryItem(_addon_id, url, list_item, isFolder = False)
        if page < photos['pages']:
            params = {'do': _DO_PHOTO,'oid': oid,'page': page + 1}
            if album: params['album'] = album
            self.root.add_folder(self.root.gui._string(400602), params)
        xbmcplugin.endOfDirectory(_addon_id)
        switch_view()

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
    def _main_video(self):
        oid = self.root.params['oid']
        self.root.add_folder(self.root.gui._string(400509), {'do': _DO_VIDEO, 'oid': oid, 'page': 1})
        self.root.add_folder(self.root.gui._string(400510), {'do': _DO_VIDEO_ALBUMS, 'oid': oid, 'page': 1})
        xbmcplugin.endOfDirectory(_addon_id)
    def _video_albums(self):
        page = int(self.root.params['page'])
        oid = self.root.params['oid']
        kwargs = {'page': page, 'extended': 1}
        albums = media_entries('video.getAlbums', self.root.conn, oid, **kwargs)
        if page < albums['pages']:
            params = {'do': _DO_VIDEO_ALBUMS,'oid': oid,'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        for a in albums['items']:
            list_item = xbmcgui.ListItem(a.info['title'])
            list_item.setInfo('video', {'title': a.info['title']})
            if 'photo_320' in a.info.keys():
                list_item.setArt({'thumb': a.info['photo_160'], 'icon': a.info['photo_160'], 'fanart': a.info['photo_320']})
            params = {'do': _DO_VIDEO, 'oid': oid, 'album': a.id, 'page': 1}
            url = self.root.url(**params)
            xbmcplugin.addDirectoryItem(_addon_id, url, list_item, isFolder = True)
        if page < albums['pages']:
            params = {'do': _DO_VIDEO_ALBUMS,'oid': oid,'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        xbmcplugin.endOfDirectory(_addon_id)
    def _video(self):
        page = int(self.root.params['page'])
        oid = self.root.params['oid']
        album = self.root.params.get('album', None)
        kwargs = {'page': page}
        if album: kwargs['album'] = album
        vids = media_entries('video.get', self.root.conn, oid, **kwargs)
        if page < vids['pages']:
            params = {'do': _DO_VIDEO,'oid': oid,'page': page + 1}
            if album: params['album'] = album
            self.root.add_folder(self.root.gui._string(400602), params)
        for v in vids['items']:
            list_item = xbmcgui.ListItem(v.info['title'])
            list_item.setInfo('video', {
                                        'title'     : v.info['title'],
                                        'duration'  : int(v.info['duration']),
                                        'plot'      : v.info['description']
                                        }
                              )
            p_key = 'photo_%d' % (max(map(lambda x: int(x.split('_')[1]), filter(lambda x: x.startswith('photo_'), v.info.keys()))),)
            list_item.setArt({'thumb': v.info['photo_130'], 'icon': v.info['photo_130'], 'fanart': v.info[p_key]})
            list_item.setProperty('IsPlayable', 'true')
            v_source = self.__get_video_source_(v)
            if v_source == _VK_VIDEO_SOURCE:
                params = {'do': _DO_PLAY_VIDEO, 'vid': v.id, 'source': _VK_VIDEO_SOURCE}
                url = self.root.url(**params)
            elif v_source == _YOUTUBE_VIDEO_SOURCE:
                if 'files' in v.info.keys():
                    y_url = v.info['files']['external']
                else:
                    y_url = v.info['player']
                s = re.compile('^http.*youtube.*(v=|\/embed\/)([^\?\&]+)[\?\&]?.*$')
                sr = s.findall(y_url)
                if len(sr) < 0:
                    raise Exception('Unknown youtube url: %s' % (y_url,))
                y_id = sr[0][1]
                url = u'plugin://plugin.video.youtube/?action=play_video&videoid=' + y_id
            else:
                continue
            xbmcplugin.addDirectoryItem(_addon_id, url, list_item, isFolder = False)
        if page < vids['pages']:
            params = {'do': _DO_VIDEO,'oid': oid,'page': page + 1}
            if album: params['album'] = album
            self.root.add_folder(self.root.gui._string(400602), params)
        xbmcplugin.endOfDirectory(_addon_id)
    def _play_video(self):
        vid = self.root.params['vid']
        src = self.root.params['source']
        v = Entry('video.get', vid, self.root.conn)
        v.set_info()
        if 'files' in v.info.keys():
            paths = {}
            if src == _VK_VIDEO_SOURCE:
                for k in v.info['files'].keys():
                    paths[k.split('_')[1]] = v.info['files'][k]   
        else:
            v_url = v.info['player']
            if src == _VK_VIDEO_SOURCE:
                paths = self.root.parse_vk_player_html(v_url)
        ### Здесь должно браться разрешение из настроек
        k = max(paths.keys())
        path = paths[k]
        play_item = xbmcgui.ListItem(path = path)
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
        oid = self.root.params['oid']
        if not c_type:
            xbmc.log('No content_type')
            return
        if int(oid) < 0:
            g = Group(oid, self.root.conn)
            g.set_info()
            header_string = u'%s [I]%s[/I]' % (self._string(400604).decode('utf-8'), g.info['name'])
            p_key = 'photo_%d' % (max(map(lambda x: int(x.split('_')[1]), filter(lambda x: x.startswith('photo_'), g.info.keys()))),)
            thumb_url = g.info[p_key]
            icon_url = g.info[p_key]
        else:
            u = User(oid, self.root.conn)
            u.set_info()
            header_string = u'%s [I]%s %s[/I]' % (self._string(400603).decode('utf-8'), u.info['last_name'], u.info['first_name'])
            p_key = 'photo_%d' % (max(map(lambda x: int(x.split('_')[1]), filter(lambda x: x.startswith('photo_'), u.info.keys()))),)
            thumb_url = u.info[p_key]
            icon_url = u.info[p_key]
        list_item = xbmcgui.ListItem(header_string)
        list_item.setArt({'thumb': thumb_url, 'icon': icon_url})
        xbmcplugin.addDirectoryItem(_addon_id, None, list_item, isFolder = False)
        if c_type == _CTYPE_VIDEO:
            self.root.add_folder(self._string(400502), {'do': _DO_MAIN_VIDEO, 'oid': oid})
        elif c_type == _CTYPE_AUDIO:
            self.root.add_folder(self._string(400503), {'do': _DO_MAIN_AUDIO, 'oid': oid})
        elif c_type == _CTYPE_IMAGE:
            self.root.add_folder(self._string(400504), {'do': _DO_MAIN_PHOTO, 'oid': oid})
        else:
            xbmc.log('Unknown content_type: %s' % (c_type,))
            return
        if int(oid) > 0:
            self.root.add_folder(self._string(400505), {'do': _DO_FRIENDS, 'oid': oid, 'page': 1})
            self.root.add_folder(self._string(400506), {'do': _DO_GROUPS, 'oid': oid, 'page': 1})
        else:
            self.root.add_folder(self._string(400512), {'do': _DO_MEMBERS, 'oid': -int(oid), 'page': 1})
        xbmcplugin.endOfDirectory(_addon_id)
    def _groups(self):
        oid = self.root.params['oid']
        page = int(self.root.params['page'])
        user = User(oid, self.root.conn)
        groups = user.groups(page = page)
        if page < groups['pages']:
            params = {'do': _DO_GROUPS, 'oid': oid, 'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        for g in groups['items']:
            list_item = xbmcgui.ListItem(g.info['name'])
            p_key = 'photo_%d' % (max(map(lambda x: int(x.split('_')[1]), filter(lambda x: x.startswith('photo_'), g.info.keys()))),)
            list_item.setArt({'thumb': g.info[p_key], 'icon': g.info[p_key]})
            params = {'do': _DO_HOME, 'oid': -g.id}
            url = self.root.url(**params)
            xbmcplugin.addDirectoryItem(_addon_id, url, list_item, isFolder = True)
        if page < groups['pages']:
            params = {'do': _DO_GROUPS, 'oid': oid, 'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        xbmcplugin.endOfDirectory(_addon_id)
    def _friends(self):
        oid = self.root.params['oid']
        page = int(self.root.params['page'])
        user = User(oid, self.root.conn)
        friends = user.friends(page = page)
        if page < friends['pages']:
            params = {'do': _DO_FRIENDS, 'oid': oid, 'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        for f in friends['items']:
            list_item = xbmcgui.ListItem(u'%s %s' % (f.info['last_name'], f.info['first_name']))
            p_key = 'photo_%d' % (max(map(lambda x: int(x.split('_')[1]), filter(lambda x: x.startswith('photo_'), f.info.keys()))),)
            list_item.setArt({'thumb': f.info[p_key], 'icon': f.info[p_key]})
            params = {'do': _DO_HOME, 'oid': f.id}
            url = self.root.url(**params)
            xbmcplugin.addDirectoryItem(_addon_id, url, list_item, isFolder = True)
        if page < friends['pages']:
            params = {'do': _DO_FRIENDS, 'oid': oid, 'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        xbmcplugin.endOfDirectory(_addon_id)
    def _members(self):
        oid = self.root.params['oid']
        page = int(self.root.params['page'])
        group = Group(oid, self.root.conn)
        members = group.members(page = page)
        if page < members['pages']:
            params = {'do': _DO_MEMBERS, 'oid': oid, 'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        for m in members['items']:
            list_item = xbmcgui.ListItem(u'%s %s' % (m.info['last_name'], m.info['first_name']))
            p_key = 'photo_%d' % (max(map(lambda x: int(x.split('_')[1]), filter(lambda x: x.startswith('photo_'), m.info.keys()))),)
            list_item.setArt({'thumb': m.info[p_key], 'icon': m.info[p_key]})
            params = {'do': _DO_HOME, 'oid': m.id}
            url = self.root.url(**params)
            xbmcplugin.addDirectoryItem(_addon_id, url, list_item, isFolder = True)
        if page < members['pages']:
            params = {'do': _DO_MEMBERS, 'oid': oid, 'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        xbmcplugin.endOfDirectory(_addon_id)
    
class KodiVk:
    conn = None
    def __init__(self):
        self.gui = KodiVkGUI(self)
        self.conn = self.__connect_()
        u_info = self.conn.users.get()[0]
        self.u = User(u_info['id'], self.conn)
        self.u.set_info()
        p = {'do': _DO_HOME}
        p['oid'] = self.u.info['id']
        if sys.argv[2]:
            p.update(dict(urlparse.parse_qsl(sys.argv[2][1:])))
        self.params = p
        self.c_type = p.get('content_type', None)
        if not self.c_type:
            cw_id = xbmcgui.getCurrentWindowId()
            if cw_id in (10006, 10024, 10025, 10028):
                self.c_type = _CTYPE_VIDEO
            elif id in (10005, 10500, 10501, 10502):
                self.c_type = _CTYPE_AUDIO
            elif id in (10002,):
                self.c_type = _CTYPE_IMAGE
    def url(self, params=dict(), **kwparams):
        if self.c_type:
            kwparams['content_type'] = self.c_type
        params.update(kwparams)
        return _addon_url + "?" + urlencode(params)
    def add_folder(self, name, params):
        url = self.url(**params)
        item = xbmcgui.ListItem(name)
        xbmcplugin.addDirectoryItem(_addon_id, url, item, isFolder = True)
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
            res[int(tup[0])] = tup[1].replace('\\', '')
        return res

if __name__ == '__main__':
    kvk = KodiVk()
    
    _DO = {
       _DO_HOME: kvk.gui._home,
       _DO_MAIN_PHOTO: kvk.gui.photos._main_photo,
       _DO_PHOTO: kvk.gui.photos._photo,
       _DO_PHOTO_ALBUMS: kvk.gui.photos._photo_albums,
       _DO_MAIN_VIDEO: kvk.gui.videos._main_video,
       _DO_VIDEO: kvk.gui.videos._video,
       _DO_VIDEO_ALBUMS: kvk.gui.videos._video_albums,
       _DO_PLAY_VIDEO: kvk.gui.videos._play_video,
       _DO_GROUPS: kvk.gui._groups,
       _DO_FRIENDS: kvk.gui._friends,
       _DO_MEMBERS: kvk.gui._members
       }
    
    _do_method = kvk.params['do']
    if _do_method in _DO.keys():
        _DO[_do_method]()
