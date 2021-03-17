# -*- coding: utf-8 -*-
import sys, os, vk, time, pickle, binascii
from math import ceil
import xbmc, xbmcplugin, xbmcaddon, xbmcgui
import urlparse
import urllib2
from urllib import urlencode
import re

_VERSION = '1.2.5'

_ADDON_NAME =   'kodi-vk.inpos.ru'
_addon      =   xbmcaddon.Addon(id = _ADDON_NAME)
_addon_id   =   int(sys.argv[1])
_addon_url  =   sys.argv[0]
_addon_path =   _addon.getAddonInfo('path').decode('utf-8')

_APP_ID = '4353740'
_SCOPE  = 'friends,photos,audio,video,groups,messages,offline'


_SETTINGS_ID_TOKEN = 'vk_token'
_SETTINGS_ID_MAX_RES = 'video_resolution'
_SETTINGS_ID_LIST_LEN = 'list_len'
_SETTINGS_ID_VIDEO_SEARCH_SORT = 'v_search_sort'
_SETTINGS_ID_VIDEO_SEARCH_HD = 'search_hd_video'
_SETTINGS_ID_VIDEO_SEARCH_ADULT = 'dont_search_adult_video'

_SETTINGS_BOOL = {'true': 1, 'false': 0}
_SETTINGS_INV_BOOL = {'true': 0, 'false': 1}

_SETTINGS_PAGE_ITEMS = int(_addon.getSetting(_SETTINGS_ID_LIST_LEN))
_SETTINGS_MAX_RES = int(_addon.getSetting(_SETTINGS_ID_MAX_RES))
_SETTINGS_VIDEO_SEARCH_SORT = int(_addon.getSetting(_SETTINGS_ID_VIDEO_SEARCH_SORT))
_SETTINGS_VIDEO_SEARCH_HD = _SETTINGS_BOOL[_addon.getSetting(_SETTINGS_ID_VIDEO_SEARCH_HD)]
_SETTINGS_VIDEO_SEARCH_ADULT = _SETTINGS_INV_BOOL[_addon.getSetting(_SETTINGS_ID_VIDEO_SEARCH_ADULT)]


_FILE_VIDEO_SEARCH_HISTORY = _ADDON_NAME + '_vsh.pkl'
_FILE_GROUP_SEARCH_HISTORY = _ADDON_NAME + '_gsh.pkl'
_FILE_USER_SEARCH_HISTORY = _ADDON_NAME + '_ush.pkl'

_USERNAME = 'vk_username'
_LOGIN_RETRY = 3
_VK_API_VERSION = '5.95'

_PHOTO_THUMB_KEY = 'photo_130'

_CTYPE_VIDEO = 'video'
_CTYPE_AUDIO = 'audio'
_CTYPE_IMAGE = 'image'

_DO_HOME = 'home'
_DO_MAIN_VIDEO = 'main_video'
_DO_VIDEO = 'video'
_DO_VIDEO_ALBUMS = 'video_albums'
_DO_MAIN_VIDEO_SEARCH = 'main_video_search'
_DO_VIDEO_SEARCH = 'video_search'
_DO_PLAY_VIDEO = 'play_video'
_DO_MAIN_AUDIO = 'main_audio'
_DO_MAIN_PHOTO = 'main_photo'
_DO_PHOTO = 'photo'
_DO_PHOTO_ALBUMS = 'photo_albums'
_DO_FRIENDS = 'friends'
_DO_GROUPS = 'groups'
_DO_MAIN_GROUP_SEARCH = 'main_group_search'
_DO_GROUP_SEARCH = 'group_search'
_DO_MEMBERS = 'members'
_DO_MAIN_USER_SEARCH = 'main_user_search'
_DO_USER_SEARCH = 'user_search'
_DO_MAIN_FAVE = 'main_fave'
_DO_FAVE_VIDEO = 'fave_video'
_DO_FAVE_PHOTO = 'fave_photo'
_DO_FAVE_GROUPS = 'fave_groups'
_DO_FAVE_USERS = 'fave_users'
_DO_LOGOUT = 'logout'

_NO_OWNER = '__no_owner__'

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
        pages = ceil(float(count) / float(page_items))
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

def get_search_history(h_file_name):
    path = os.path.join(xbmc.translatePath('special://temp/').decode('utf-8'), h_file_name.decode('utf-8'))
    if not os.path.exists(path):
        return []
    with open(path, 'rb') as f:
        history = pickle.load(f)
    return history

def put_search_history(history, h_file_name):
    path = os.path.join(xbmc.translatePath('special://temp/').decode('utf-8'), h_file_name.decode('utf-8'))
    with open(path, 'wb') as f:
        pickle.dump(history, f, -1)

def media_entries(e_method, conn, oid, **kwargs):
    page_items = kwargs.pop('page_items', _SETTINGS_PAGE_ITEMS)
    page = kwargs.pop('page', 1)
    album = kwargs.pop('album', None)
    kwargs.update({
              'offset': ((page_items * page) - page_items),
              'count': page_items
              })
    if oid != _NO_OWNER:
        kwargs['owner_id'] = oid
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
        if e_method.split('.')[-1] in ['getAlbums', 'getUsers', 'getLinks']:
            entry_id = str(i['id'])
        else:
            entry_id = str(i['owner_id']) + '_' + str(i['id'])
        e = Entry(e_method, entry_id, conn)
        e.info = i
        l.append(e)
    del entries['count']
    del entries['items']
    res = {'pages': pages, 'total': count, 'items': l}
    for k in entries.keys():
        res[k] = entries[k]
    return res

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
        pages = ceil(float(count) / float(page_items))
        l = []
        for i in f['items']:
            u = User(i['id'], self.conn)
            u.info = i
            l.append(u)
        return {'pages': pages, 'total': count, 'items': l}
    def user_search(self, q = '', page_items = _SETTINGS_PAGE_ITEMS, page = 1):
        usr = self.conn.users.search(q = q,
                                   offset = ((page_items * page) - page_items),
                                   count = page_items,
                                   fields = 'first_name,last_name,photo_50,photo_100,photo_200')
        count = usr['count']
        pages = ceil(float(count) / float(page_items))
        l = []
        for i in usr['items']:
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
        pages = ceil(float(count) / float(page_items))
        l = []
        for i in gr['items']:
            if i['is_closed'] > 0 and i['is_member'] == 0: continue
            g = Group(i['id'], self.conn)
            g.info = i
            l.append(g)
        return {'pages': pages, 'total': count, 'items': l}
    def group_search(self, q = '', page_items = _SETTINGS_PAGE_ITEMS, page = 1):
        gr = self.conn.groups.search(q = q,
                                 offset = ((page_items * page) - page_items),
                                 count = page_items)
        count = gr['count']
        pages = ceil(float(count) / float(page_items))
        l = []
        for i in gr['items']:
            if i['is_closed'] > 0 and i['is_member'] == 0: continue
            g = Group(i['id'], self.conn)
            g.info = i
            l.append(g)
        return {'pages': pages, 'total': count, 'items': l}

class KodiVKGUIFave(object):
    def __init__(self, root):
        self.root = root
    def _main_fave(self):
        if self.root.c_type == _CTYPE_VIDEO:
            self.root.add_folder(self.root.gui._string(400502), {'do': _DO_FAVE_VIDEO, 'page': 1})
        elif self.root.c_type == _CTYPE_IMAGE:
            self.root.add_folder(self.root.gui._string(400504), {'do': _DO_FAVE_PHOTO, 'page': 1})
        self.root.add_folder(self.root.gui._string(400513), {'do': _DO_FAVE_USERS, 'page': 1})
        self.root.add_folder(self.root.gui._string(400506), {'do': _DO_FAVE_GROUPS, 'page': 1})
        xbmcplugin.endOfDirectory(_addon_id)
    def _video(self):
        page = int(self.root.params['page'])
        kwargs = {'page': page, 'extended': 1}
        vids = media_entries('fave.getVideos', self.root.conn, _NO_OWNER, **kwargs)
        if page < vids['pages']:
            params = {'do': _DO_FAVE_VIDEO, 'page': page + 1}
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
            if 'files' in v.info.keys():
                if 'external' in v.info['files']:
                    v_source = self.root.gui.videos._get_video_source(v.info['files']['external'])
                else:
                    v_source = _VK_VIDEO_SOURCE
            else:
                v_source = self.root.gui.videos._get_video_source(v.info['player'])
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
                    xbmc.log('WARN: Unknown youtube url: %s' % (y_url,))
                    continue
                y_id = sr[0][1]
                url = u'plugin://plugin.video.youtube/?action=play_video&videoid=' + y_id
            else:
                continue
            xbmcplugin.addDirectoryItem(_addon_id, url, list_item, isFolder = False)
        if page < vids['pages']:
            params = {'do': _DO_FAVE_VIDEO, 'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        xbmcplugin.endOfDirectory(_addon_id)
    def _photo(self):
        page = int(self.root.params['page'])
        kwargs = {'page': page}
        photos = media_entries('photos.getAll', self.root.conn, _NO_OWNER, **kwargs)
        if page < photos['pages']:
            params = {'do': _DO_FAVE_PHOTO, 'page': page + 1}
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
            params = {'do': _DO_FAVE_PHOTO, 'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        xbmcplugin.endOfDirectory(_addon_id)
        switch_view()
    def _users(self):
        page = int(self.root.params['page'])
        users = media_entries('fave.getUsers', self.root.conn, _NO_OWNER, page = page)
        if page < users['pages']:
            params = {'do': _DO_FAVE_USERS, 'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        for u in users['items']:
            list_item = xbmcgui.ListItem(u'%s %s' % (u.info['last_name'], u.info['first_name']))
            #p_key = 'photo_%d' % (max(map(lambda x: int(x.split('_')[1]), filter(lambda x: x.startswith('photo_'), m.info.keys()))),)
            #list_item.setArt({'thumb': m.info[p_key], 'icon': m.info[p_key]})
            params = {'do': _DO_HOME, 'oid': u.id}
            url = self.root.url(**params)
            xbmcplugin.addDirectoryItem(_addon_id, url, list_item, isFolder = True)
        if page < users['pages']:
            params = {'do': _DO_FAVE_USERS, 'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        xbmcplugin.endOfDirectory(_addon_id)
    def _groups(self):
        page = int(self.root.params['page'])
        links = media_entries('fave.getLinks', self.root.conn, _NO_OWNER, page = page)
        if page < links['pages']:
            params = {'do': _DO_FAVE_GROUPS, 'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        for l in links['items']:
            l_id = l.info['id'].split('_')
            if l_id[0] == '2':
                list_item = xbmcgui.ListItem(l.info['title'])
                p_key = 'photo_%d' % (max(map(lambda x: int(x.split('_')[1]), filter(lambda x: x.startswith('photo_'), l.info.keys()))),)
                list_item.setArt({'thumb': l.info[p_key], 'icon': l.info[p_key]})
                params = {'do': _DO_HOME, 'oid': -int(l_id[-1])}
                url = self.root.url(**params)
                xbmcplugin.addDirectoryItem(_addon_id, url, list_item, isFolder = True)
        if page < links['pages']:
            params = {'do': _DO_FAVE_GROUPS, 'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        xbmcplugin.endOfDirectory(_addon_id)

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
            num = (_SETTINGS_PAGE_ITEMS * (page - 1)) + index + 1
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
    def _get_video_source(self, v_url):
        is_vk_url_re = re.compile('https?\:\/\/[^\/]*vk.com\/.*')
        is_youtube_url_re = re.compile('https\:\/\/www.youtube.com\/.*')
        if len(is_vk_url_re.findall(v_url)) > 0: return _VK_VIDEO_SOURCE
        if len(is_youtube_url_re.findall(v_url)) > 0: return _YOUTUBE_VIDEO_SOURCE
        return _UNKNOWN_VIDEO_SOURCE
    def _main_video_search(self):
        page = int(self.root.params['page'])
        self.root.add_folder(self.root.gui._string(400516), {'do': _DO_VIDEO_SEARCH, 'q':'none', 'page': 1})
        history = get_search_history(_FILE_VIDEO_SEARCH_HISTORY)
        count = len(history)
        pages = int(ceil(count / float(_SETTINGS_PAGE_ITEMS)))
        if page < pages:
            params = {'do': _DO_MAIN_VIDEO_SEARCH, 'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        h_start = _SETTINGS_PAGE_ITEMS * (page -1)
        h_end = h_start + _SETTINGS_PAGE_ITEMS
        history = history[h_start:h_end]
        for h in history:
            query_hex = binascii.hexlify(pickle.dumps(h, -1))
            list_item = xbmcgui.ListItem(h)
            params = {'do': _DO_VIDEO_SEARCH, 'q': query_hex, 'page': 1}
            url = self.root.url(**params)
            xbmcplugin.addDirectoryItem(_addon_id, url, list_item, isFolder = True)
        if page < pages:
            params = {'do': _DO_MAIN_VIDEO_SEARCH, 'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        xbmcplugin.endOfDirectory(_addon_id)
    def _video_search(self):
        page = int(self.root.params['page'])
        q = self.root.params['q']
        if q == 'none':
            s_win = xbmc.Keyboard()
            s_win.setHeading(self.root.gui._string(400515))
            s_win.setHiddenInput(False)
            s_win.doModal()
            if s_win.isConfirmed():
                q = s_win.getText()
            else:
                self.root.gui.notify(self.root.gui._string(400525), '')
                return
        else:
            q = pickle.loads(binascii.unhexlify(q))
        history = get_search_history(_FILE_VIDEO_SEARCH_HISTORY)
        try:
            del history[history.index(q)]
        except ValueError:
            pass
        history = [q] + history
        put_search_history(history, _FILE_VIDEO_SEARCH_HISTORY)
        query_hex = binascii.hexlify(pickle.dumps(q, -1))
        kwargs = {
                  'page': page,
                  'sort': _SETTINGS_VIDEO_SEARCH_SORT,
                  'hd'  : _SETTINGS_VIDEO_SEARCH_HD,
                  'adult': _SETTINGS_VIDEO_SEARCH_ADULT,
                  'q': q,
                  'extended': 1
                  }
        search_res = media_entries('video.search', self.root.conn, _NO_OWNER, **kwargs)
        if page < search_res['pages']:
            params = {'do': _DO_VIDEO_SEARCH, 'q': query_hex, 'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        self.__create_video_list_(search_res)
        if page < search_res['pages']:
            params = {'do': _DO_VIDEO_SEARCH, 'q': query_hex, 'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        xbmcplugin.endOfDirectory(_addon_id)
    def _main_video(self):
        oid = self.root.params['oid']
        self.root.add_folder(self.root.gui._string(400509), {'do': _DO_VIDEO, 'oid': oid, 'page': 1})
        self.root.add_folder(self.root.gui._string(400510), {'do': _DO_VIDEO_ALBUMS, 'oid': oid, 'page': 1})
        if int(oid) == self.root.u.id:
            self.root.add_folder(self.root.gui._string(400515), {'do': _DO_MAIN_VIDEO_SEARCH, 'page': 1})
        xbmcplugin.endOfDirectory(_addon_id)
    def __create_video_list_(self, vids):
        for v in vids['items']:
            list_item = xbmcgui.ListItem(v.info['title'])
            oid = v.info['owner_id']
            if int(oid) < 0:
                gid = oid * -1
                g = filter(lambda x: x['id'] == gid, vids['groups'])[0]
                cm_title = u'%s [I]%s[/I]' % (self.root.gui._string(400604).decode('utf-8'), g['name'])
            else:
                u = filter(lambda x: x['id'] == oid, vids['profiles'])[0]
                cm_title = u'%s [I]%s %s[/I]' % (self.root.gui._string(400603).decode('utf-8'), u['last_name'], u['first_name'])
            cm_params = {'do': _DO_HOME, 'oid': oid}
            cm_url = self.root.url(**cm_params)
            list_item.addContextMenuItems([(cm_title, 'xbmc.Container.update(%s)' % (cm_url,))])
            list_item.setInfo('video', {
                                        'title'     : v.info['title'],
                                        'duration'  : int(v.info['duration']),
                                        'plot'      : v.info['description']
                                        }
                              )
            p_key = 'photo_%d' % (max(map(lambda x: int(x.split('_')[1]), filter(lambda x: x.startswith('photo_'), v.info.keys()))),)
            list_item.setArt({'thumb': v.info['photo_130'], 'icon': v.info['photo_130'], 'fanart': v.info[p_key]})
            list_item.setProperty('IsPlayable', 'true')
            if 'files' in v.info.keys():
                if 'external' in v.info['files']:
                    v_source = self._get_video_source(v.info['files']['external'])
                else:
                    v_source = _VK_VIDEO_SOURCE
            else:
                v_source = self._get_video_source(v.info['player'])
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
                    xbmc.log('WARN: Unknown youtube url: %s' % (y_url,))
                    continue
                y_id = sr[0][1]
                url = u'plugin://plugin.video.youtube/?action=play_video&videoid=' + y_id
            else:
                continue
            xbmcplugin.addDirectoryItem(_addon_id, url, list_item, isFolder = False)
    def _video_albums(self):
        page = int(self.root.params['page'])
        oid = self.root.params['oid']
        kwargs = {
                    'page': page,
                    'extended': 1
                    }
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
        kwargs = {'page': page, 'extended': 1}
        if album: kwargs['album'] = album
        vids = media_entries('video.get', self.root.conn, oid, **kwargs)
        if page < vids['pages']:
            params = {'do': _DO_VIDEO,'oid': oid,'page': page + 1}
            if album: params['album'] = album
            self.root.add_folder(self.root.gui._string(400602), params)
        self.__create_video_list_(vids)
        if page < vids['pages']:
            params = {'do': _DO_VIDEO,'oid': oid,'page': page + 1}
            if album: params['album'] = album
            self.root.add_folder(self.root.gui._string(400602), params)
        xbmcplugin.endOfDirectory(_addon_id)
    def _play_video(self):
        vid = self.root.params['vid']
        src = self.root.params['source']
        v = Entry('video.get', vid, self.root.conn)
        try:
            v.set_info()
        except:
            self.root.gui.notify(self.root.gui._string(400524), '')
            return
        if 'files' in v.info.keys():
            paths = {}
            if src == _VK_VIDEO_SOURCE:
                for k in v.info['files'].keys():
                    if '_' not in k:
                        try:
                            local_idx = int(k)
                        except:
                            continue
                    else:
                        local_idx = int(k.split('_')[1])
                    paths[local_idx] = v.info['files'][k]
        else:
            v_url = v.info['player']
            if src == _VK_VIDEO_SOURCE:
                paths = self.root.parse_vk_player_html(v_url)
        ### Здесь должно браться разрешение из настроек
        k = max(filter(lambda x: x <= _SETTINGS_MAX_RES, paths.keys()))
        path = paths[k]
        play_item = xbmcgui.ListItem(path = path)
        xbmcplugin.setResolvedUrl(_addon_id, True, listitem = play_item)

class KodiVkGUI:
    '''Окошки, диалоги, сообщения'''
    def __init__(self, root):
        self.root = root
        self.photos = KodiVKGUIPhotos(self.root)
        self.videos = KodiVKGUIVideos(self.root)
        self.faves = KodiVKGUIFave(self.root)
    def notify(self,title, msg):
        dialog = xbmcgui.Dialog()
        dialog.notification(title, msg,
                            xbmcgui.NOTIFICATION_WARNING, 3000)
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
        h_url = self.root.url({'do': _DO_HOME, 'oid': oid})
        xbmcplugin.addDirectoryItem(_addon_id, h_url, list_item, isFolder = True)
        if c_type == _CTYPE_VIDEO:
            self.root.add_folder(self._string(400502), {'do': _DO_MAIN_VIDEO, 'oid': oid})
        #elif c_type == _CTYPE_AUDIO:
        #    self.root.add_folder(self._string(400503), {'do': _DO_MAIN_AUDIO, 'oid': oid})
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
        if oid == self.root.u.id:
            self.root.add_folder(self._string(400514), {'do': _DO_MAIN_FAVE})
            xbmcplugin.addDirectoryItem(_addon_id, None, xbmcgui.ListItem(''), isFolder = False)
            xbmcplugin.addDirectoryItem(_addon_id, None, xbmcgui.ListItem(''), isFolder = False)
            xbmcplugin.addDirectoryItem(_addon_id, None, xbmcgui.ListItem(''), isFolder = False)
            self.root.add_folder(self._string(400526), {'do': _DO_LOGOUT})
        xbmcplugin.endOfDirectory(_addon_id)
    def __create_group_list_(self, groups):
        for g in groups['items']:
            list_item = xbmcgui.ListItem(g.info['name'])
            p_key = 'photo_%d' % (max(map(lambda x: int(x.split('_')[1]), filter(lambda x: x.startswith('photo_'), g.info.keys()))),)
            list_item.setArt({'thumb': g.info[p_key], 'icon': g.info[p_key]})
            params = {'do': _DO_HOME, 'oid': -g.id}
            url = self.root.url(**params)
            xbmcplugin.addDirectoryItem(_addon_id, url, list_item, isFolder = True)
    def _groups(self):
        oid = self.root.params['oid']
        page = int(self.root.params['page'])
        if int(oid) == self.root.u.id:
            self.root.add_folder(self.root.gui._string(400515), {'do': _DO_MAIN_GROUP_SEARCH, 'page': 1})
        user = User(oid, self.root.conn)
        groups = user.groups(page = page)
        if page < groups['pages']:
            params = {'do': _DO_GROUPS, 'oid': oid, 'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        self.__create_group_list_(groups)
        if page < groups['pages']:
            params = {'do': _DO_GROUPS, 'oid': oid, 'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        xbmcplugin.endOfDirectory(_addon_id)
    def __create_user_list_(self, users):
        for f in users['items']:
            list_item = xbmcgui.ListItem(u'%s %s' % (f.info['last_name'], f.info['first_name']))
            p_key = 'photo_%d' % (max(map(lambda x: int(x.split('_')[1]), filter(lambda x: x.startswith('photo_'), f.info.keys()))),)
            list_item.setArt({'thumb': f.info[p_key], 'icon': f.info[p_key]})
            params = {'do': _DO_HOME, 'oid': f.id}
            url = self.root.url(**params)
            xbmcplugin.addDirectoryItem(_addon_id, url, list_item, isFolder = True)
    def _friends(self):
        oid = self.root.params['oid']
        page = int(self.root.params['page'])
        if int(oid) == self.root.u.id:
            self.root.add_folder(self.root.gui._string(400515), {'do': _DO_MAIN_USER_SEARCH, 'page': 1})
        user = User(oid, self.root.conn)
        friends = user.friends(page = page)
        if page < friends['pages']:
            params = {'do': _DO_FRIENDS, 'oid': oid, 'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        self.__create_user_list_(friends)
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
    def __create_user_group_search_page_(self, do_current, do_target, h_file):
        page = int(self.root.params['page'])
        self.root.add_folder(self.root.gui._string(400516), {'do': do_target, 'q':'none', 'page': 1})
        history = get_search_history(h_file)
        count = len(history)
        pages = int(ceil(count / float(_SETTINGS_PAGE_ITEMS)))
        if page < pages:
            params = {'do': do_current, 'page': page + 1}
            self.root.add_folder(self._string(400602), params)
        h_start = _SETTINGS_PAGE_ITEMS * (page -1)
        h_end = h_start + _SETTINGS_PAGE_ITEMS
        history = history[h_start:h_end]
        for h in history:
            query_hex = binascii.hexlify(pickle.dumps(h, -1))
            list_item = xbmcgui.ListItem(h)
            params = {'do': do_target, 'q': query_hex, 'page': 1}
            url = self.root.url(**params)
            xbmcplugin.addDirectoryItem(_addon_id, url, list_item, isFolder = True)
        if page < pages:
            params = {'do': do_current, 'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        xbmcplugin.endOfDirectory(_addon_id)
    def _main_group_search(self):
        self.__create_user_group_search_page_(_DO_MAIN_GROUP_SEARCH, _DO_GROUP_SEARCH, _FILE_GROUP_SEARCH_HISTORY)
    def _group_search(self):
        page = int(self.root.params['page'])
        q = self.root.params['q']
        if q == 'none':
            s_win = xbmc.Keyboard()
            s_win.setHeading(self._string(400515))
            s_win.setHiddenInput(False)
            s_win.doModal()
            if s_win.isConfirmed():
                q = s_win.getText()
            else:
                self.notify(self._string(400525), '')
                return
        else:
            q = pickle.loads(binascii.unhexlify(q))
        history = get_search_history(_FILE_GROUP_SEARCH_HISTORY)
        try:
            del history[history.index(q)]
        except ValueError:
            pass
        history = [q] + history
        put_search_history(history, _FILE_GROUP_SEARCH_HISTORY)
        query_hex = binascii.hexlify(pickle.dumps(q, -1))
        kwargs = {
                  'page': page,
                  'q': q
                  }
        u = User(self.root.u.id, self.root.conn)
        search_res = u.group_search(**kwargs)
        if page < search_res['pages']:
            params = {'do': _DO_GROUP_SEARCH, 'q': query_hex, 'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        self.__create_group_list_(search_res)
        if page < search_res['pages']:
            params = {'do': _DO_GROUP_SEARCH, 'q': query_hex, 'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        xbmcplugin.endOfDirectory(_addon_id)
    def _main_user_search(self):
        self.__create_user_group_search_page_(_DO_MAIN_USER_SEARCH, _DO_USER_SEARCH, _FILE_USER_SEARCH_HISTORY)
    def _user_search(self):
        page = int(self.root.params['page'])
        q = self.root.params['q']
        if q == 'none':
            s_win = xbmc.Keyboard()
            s_win.setHeading(self.root.gui._string(400515))
            s_win.setHiddenInput(False)
            s_win.doModal()
            if s_win.isConfirmed():
                q = s_win.getText()
            else:
                self.notify(self._string(400525), '')
                return
        else:
            q = pickle.loads(binascii.unhexlify(q))
        history = get_search_history(_FILE_USER_SEARCH_HISTORY)
        try:
            del history[history.index(q)]
        except ValueError:
            pass
        history = [q] + history
        put_search_history(history, _FILE_USER_SEARCH_HISTORY)
        query_hex = binascii.hexlify(pickle.dumps(q, -1))
        kwargs = {
                  'page': page,
                  'q': q
                  }
        u = User(self.root.u.id, self.root.conn)
        search_res = u.user_search(**kwargs)
        if page < search_res['pages']:
            params = {'do': _DO_USER_SEARCH, 'q': query_hex, 'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        self.__create_user_list_(search_res)
        if page < search_res['pages']:
            params = {'do': _DO_USER_SEARCH, 'q': query_hex, 'page': page + 1}
            self.root.add_folder(self.root.gui._string(400602), params)
        xbmcplugin.endOfDirectory(_addon_id)
    def _logout(self):
        dialog = xbmcgui.Dialog()
        ret = dialog.yesno(self._string(400526), self._string(400527), nolabel=self._string(400529), yeslabel=self._string(400528))
        if ret:
            _addon.setSetting(_SETTINGS_ID_TOKEN, '')
            xbmc.executebuiltin("XBMC.Container.Update(path,replace)")
            xbmc.executebuiltin("XBMC.ActivateWindow(Home)")
        else:
            return
class KodiVk:
    conn = None
    def __init__(self):
        self.gui = KodiVkGUI(self)
        self.conn = self.__connect_()
        if not self.conn: raise Exception()
        u_info = self.conn.users.get()[0]
        self.u = User(u_info['id'], self.conn)
        self.u.set_info()
        p = {'do': _DO_HOME}
        if sys.argv[2]:
            p.update(dict(urlparse.parse_qsl(sys.argv[2][1:])))
        p['oid'] = int(p.get('oid', self.u.info['id']))
        self.params = p
        if 'content_type' not in self.params.keys():
            cw_id = xbmcgui.getCurrentWindowId()
            if cw_id in (10006, 10024, 10025, 10028):
                self.params['content_type'] = _CTYPE_VIDEO
            #elif id in (10005, 10500, 10501, 10502):
            #    self.params['content_type'] = _CTYPE_AUDIO
            elif id in (10002,):
                self.params['content_type'] = _CTYPE_IMAGE
        self.c_type = self.params.get('content_type', None)
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
        token = _addon.getSetting(_SETTINGS_ID_TOKEN)
        conn = Connection(_APP_ID, access_token = token)
        try:
            tmp__ = conn.users.get()[0]
        except vk.exceptions.VkAPIError, e:
            if e.code == 5:
                token = None
            else:
                raise
        if not token:
            token = None
            count = _LOGIN_RETRY
            while not token and count > 0:
                count -= 1
                try:
                    login, password = self.gui._login_form()
                except:
                    self.gui.notify(self.gui._string(400525), '')
                try:
                    conn = Connection(_APP_ID, login, password, scope = _SCOPE)
                    token = conn.conn._session.access_token
                    _addon.setSetting(_SETTINGS_ID_TOKEN, token)
                except vk.api.VkAuthError:
                    continue
            if not token:
                return
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
    try:
        kvk = KodiVk()
    except Exception, e:
        sys.exit()
    _DO = {
       _DO_HOME: kvk.gui._home,
       _DO_MAIN_PHOTO: kvk.gui.photos._main_photo,
       _DO_PHOTO: kvk.gui.photos._photo,
       _DO_PHOTO_ALBUMS: kvk.gui.photos._photo_albums,
       _DO_MAIN_VIDEO: kvk.gui.videos._main_video,
       _DO_VIDEO: kvk.gui.videos._video,
       _DO_VIDEO_ALBUMS: kvk.gui.videos._video_albums,
       _DO_PLAY_VIDEO: kvk.gui.videos._play_video,
       _DO_MAIN_VIDEO_SEARCH: kvk.gui.videos._main_video_search,
       _DO_VIDEO_SEARCH: kvk.gui.videos._video_search,
       _DO_GROUPS: kvk.gui._groups,
       _DO_MAIN_GROUP_SEARCH: kvk.gui._main_group_search,
       _DO_GROUP_SEARCH: kvk.gui._group_search,
       _DO_FRIENDS: kvk.gui._friends,
       _DO_MAIN_USER_SEARCH:kvk.gui._main_user_search,
       _DO_USER_SEARCH: kvk.gui._user_search,
       _DO_MEMBERS: kvk.gui._members,
       _DO_MAIN_FAVE: kvk.gui.faves._main_fave,
       _DO_FAVE_VIDEO: kvk.gui.faves._video,
       _DO_FAVE_PHOTO: kvk.gui.faves._photo,
       _DO_FAVE_USERS: kvk.gui.faves._users,
       _DO_FAVE_GROUPS: kvk.gui.faves._groups,
       _DO_LOGOUT: kvk.gui._logout
       }

    _do_method = kvk.params['do']
    if _do_method in _DO.keys():
        _DO[_do_method]()
