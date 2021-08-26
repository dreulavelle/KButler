from os import path, environ, remove, walk, unlink, listdir
from re import sub
from psutil import process_iter
from shutil import rmtree
from zipfile import ZIP_DEFLATED, ZipFile
from paramiko import Transport, SFTPClient
from dropbox import Dropbox, files
from dropbox.files import WriteMode
from bs4 import BeautifulSoup
from requests import get
from tqdm import tqdm
from configparser import ConfigParser
import xml.etree.ElementTree as ET

VERSION = '0.7.2'

try: # Set Variables. [WARNING] ONLY change if you know what you're doing!
    config = ConfigParser()
    config.read('config.ini')
    exclude_root = ['addons', 'userdata']
    kodipath = path.expandvars('%appdata%\Kodi\\')
    user = path.expandvars('%userprofile%')
    userdata_path = path.expandvars('%appdata%\Kodi\\userdata\\')
    addons_path = path.expandvars('%appdata%\Kodi\\addons\\')
    addn_data = path.join(userdata_path, 'addon_data')
    sources_file = path.join(userdata_path, 'sources.xml')
    desktop = path.expandvars('%userprofile%\Desktop\\')
    temp_dir = environ.get('TEMP')
    temp_build = path.join(temp_dir + "\\builds.txt")
    dbase = path.join(userdata_path + "\\Database")
    thumb_dir = path.join(userdata_path + "\\Thumbnails")
    uploadzip = int(config['SETTINGS']['uploadzip']) # TODO
    uploadbuildtxt = int(config['SETTINGS']['uploadbuildtxt']) # TODO
    db_token = config['DROPBOX']['db_token']
    remote_builds = config['BUILDFILE']['remote_build_txt']
    localbuild = config['BUILDFILENAME']['localbuild'] # TODO
    sftp_host = config['SFTP']['sftp_host']  
    sftp_username = config['SFTP']['sftp_username'] 
    sftp_password = config['SFTP']['sftp_password']
    sftp_remotepath = config['SFTP']['sftp_remotepath']
    sftp_remotebuilds = config['DROPBOX']['sftp_remotebuilds']
except: 
    print('[ERROR] config.ini File Missing. Exiting!')
    print('You can get an example config.ini at:')
    print('https://github.com/dreulavelle/KButler/blob/KButler/config_example.ini')
    print('Save this to the same directory as this program and rename to config.ini')
    print('[WARNING] Make sure to edit the values! Then you should be all set!')
    exit()

if path.isfile(temp_build):
    temp_exists = True
else:
    temp_exists = False

is_running = "kodi.exe" in (p.name() for p in process_iter())

def valid_choice(msg: str, exit_opt: int) -> None: # returns an integer
    while True:
        try:
            num = input(msg)
            if num.upper() == 'C':
                return 'C'
            elif int(num) > exit_opt or int(num) == 0 or int(num) < 0:
                print(f'Please choose between 1 and {exit_opt}. Or C to Cancel')
            elif int(num) <= exit_opt:
                return int(num)
            else:
                raise ValueError
        except ValueError:
            print(f'Please choose between 1 and {exit_opt}. Or C to Cancel')

def valid_yn(msg: str) -> None: # returns 'Y' or 'N'
    while True:
        try:
            option = input(msg)
            if option.isalpha() == False:
                print(f'Please choose [Y]es or [N]o.')
            elif option.upper() == 'Y' or option.upper() == 'N':
                return option.upper()
            else:
                raise ValueError
        except ValueError:
            print(f'Please choose [Y]es or [N]o.')

def kill_kodi():
    if is_running:
        print('- Killing Kodi Process')
        for proc in process_iter():
            if 'kodi' in proc.name():
                proc.kill()

def choices_menu(options, msg='Make Selection'):
    # options = list OR dict
    print(f'\n   {msg}')
    print('~' * 25)
    for idx, item in enumerate(options):
        idx += 1
        print(f'{idx}. {item}')
    print(f'C. Cancel')
    print('~' * 25)
    option = valid_choice('Option: ', idx)
    if option == 'C':
            return option
    for idx, items in enumerate(options):
        if option == idx + 1:
            return items

def clean_kodi():
    print('\n[STARED] Cleaning Process')
    print('- Checking Kodi Process')
    if is_running:
        kill_kodi()
    print('- Cleaning Root Folder')
    for item in listdir(kodipath):
        if item not in exclude_root:
            try: rmtree(path.join(kodipath, item))
            except: unlink(path.join(kodipath, item))
    print('- Cleaning Packages')
    print('- Cleaning Temp')
    adn_pkgs = path.join(addons_path, 'packages')
    adn_temp = path.join(addons_path, 'temp')
    rmdirs = [adn_pkgs, adn_temp]
    for fld in rmdirs:
        try: rmtree(fld)
        except FileNotFoundError as f: pass
    clean_thumbs('- Cleaning Thumbnails')
    print('- Cleaning Caches')
    clean_cache()
    includes = ['Textures']
    for dirpath, dirnames, filenames in walk(dbase):
        for files in filenames:
            if files.startswith(tuple(includes)):
                print(f'-- Removing DB: {path.join(dirpath, files)}')
                unlink(path.join(dirpath, files))
    clean_thumbs()
    print('[DONE] Cleaning Process\n')

def fresh_install():
    print('Fresh Install Kodi\n')
    if is_running:
        kill_kodi()
    rmtree(kodipath)
    return

def return_mb_size(file):
    size = path.getsize(file)
    return print('File Size: ' + str(round(size / (1024 * 1024), 3)) + ' MB')

def zip_kodi(zipname_path: str) -> None:
    if zipname_path is None or path.isdir(zipname_path):
        print("No File Given to Zip. Closing.")
        return
    print(f"Zipping Build in: {zipname_path}")
    length = len(kodipath)
    with ZipFile(zipname_path, 'w', allowZip64=True, compression=ZIP_DEFLATED) as zip:
        for root, dirs, files in walk(kodipath):
            folder = root[length:] # path without "parent"
            for file in files:
                zip.write(path.join(root, file), path.join(folder, file))
    name = path.basename(zipname_path)
    print(f'{name} Build Created!')
    return_mb_size(zipname_path)
    return

def fetch_builds():
    # using remote builds.txt file
    entries = {}
    with get(remote_builds, stream=True) as r:
        soup = BeautifulSoup(r.content, 'lxml')
        contents = soup.text.splitlines() 
        current_name = ''
        for c in contents:
            if len(c.strip()) > 0:
                data = c.split('=')
                if data[0] == 'name':
                    entries[data[1]] = {}
                    current_name = data[1]
                else:
                    data[1] = sub(r'\?dl', '?dl=1"', data[1])
                    entries[current_name][data[0]] = data[1]
                    try:
                        filename = path.basename(data[1]).replace('?dl=1"', '')
                        if filename.endswith('.zip'):
                            entries[current_name]['filename'] = filename
                        else:
                            raise Exception
                    except: 
                        filename = path.basename(data[1])
                        if filename.endswith('.zip'):
                            entries[current_name]['filename'] = filename
    return entries

def fetch_urls(show: bool) -> False:
    builds = fetch_builds()
    urls = {}
    for n, data in builds.items():
        version = data['version']
        url = data['url'].removeprefix('"').removesuffix('"')
        filename = data['filename']
        urls[filename] = url
        show_ver = version.removeprefix('"').removesuffix('"')
        is_adult = data['adult'].removeprefix('"').removesuffix('"')
        k_ver = data['kodi'].removeprefix('"').removesuffix('"')
        if show:
            print(f'{n} [Version: {show_ver}] [Kodi: {k_ver}] [Adult: {is_adult}]')
    return urls

def return_key_to_change():
    choices = ['name', 'version', 'url', 'minor', 'gui', 'kodi', 'theme', 
               'icon', 'fanart', 'preview', 'adult', 'info', 'description']
    key = choices_menu(choices, msg='Select Key To Change')
    if key == 'C':
        return False
    else:
        return key

def return_option_from_builds(show=False):
    # using remote builds.txt file
    # returns: index, name, version, url, description
    builds = fetch_builds()
    name = choices_menu(builds)
    if name == 'C':
        return
    else:
        version = builds[name]['version']
        url = builds[name]['url']
        description = builds[name]['description']
        if show:
            stripped = name.removeprefix('"').removesuffix('"')
            print(f'Build: {stripped}\nCurrent Version: {version}\nURL: {url}')
        return name, version, url, description

def filename_from_dbox():
    dbx = Dropbox(db_token, timeout=900)
    response = dbx.files_list_folder(sftp_remotebuilds)
    fnames = []
    paths = []
    for i in response.entries:
        fnames.append(i.name)
        paths.append(i.path_display)
    print('Select File From Dropbox')
    print('~' * 25)
    for idx, item in enumerate(fnames):
        idx += 1
        print(f'{idx}. {item}')
    print('~' * 25)
    option = valid_choice('Option: ', idx)
    for idx, items in enumerate(fnames):
        if option == idx + 1:
            fname = items
            path = paths[idx]

    return fname, path

def change_build_entry(name: str, key: str, value: str, entries: dict) -> None:
    # name = build name in builds.txt
    # key = key to change
    # value = new value
    # entries = builds.txt as dict
    if (name or key or value or entries) is None:
        return "[ERROR] Missing or Incorrect Argument"
    values = entries[name]
    if key in values:
        values[key] = value
        entries = values
    else:
        return "[ERROR] Key not found in entry"

def change_entry():
    entries = fetch_builds()
    name = return_option_from_builds(show=False)[0]
    key = return_key_to_change()
    if key == 'C':
        return
    rq_name = name.removeprefix('"').removesuffix('"')
    oldkey = entries[name][key].removeprefix('"').removesuffix('"')
    print(f'\nChanging {key.title()} for {rq_name}')
    print(f'Old {key}: {oldkey}')
    value = input(f'New {key}: ')
    change = f'"{value}"'
    change_build_entry(name, key, change, entries)
    craft_build(entries)
    print()

def get_shared_links_db():
    dbox_shared = {}
    dbx = Dropbox(db_token, timeout=900)
    response = dbx.files_list_folder(sftp_remotebuilds)
    for i in response.entries:
        dbox_shared[i.name] = {}
        dbox_shared[i.name]['url'] = None
        dbox_shared[i.name]['path'] = i.path_display
    for name in dbox_shared.keys():
        content = dbx.sharing_list_shared_links(dbox_shared[name]['path'])
        for link in content.links:
            dbox_shared[name]['url'] = sub(r'\?dl\=0', '?dl=1', link.url)
    return dbox_shared

def create_share_link(remote_filepath: str, show: bool) -> None or False:
    dbx = Dropbox(db_token)
    link = dbx.sharing_create_shared_link(remote_filepath)
    url = link.url
    dl_url = sub(r'\?dl\=0', '?dl=1', url)
    if show:
        print(dl_url)
    return dl_url

def check_db_shares():
    dbox_shared = get_shared_links_db()
    missing_urls = 0
    for k, v in dbox_shared.items():
        url = v['url']
        if url is None:
            path = v['path']
            try: create_share_link(path, show=False) # create urls if none exists
            finally: missing_urls += 1
    if missing_urls > 0:
        print(f'Creating share links for {missing_urls} missing URLs in Dropbox.')
    else:
        pass

def automate_shared_links():
    # Automatically create/get URL's and fix builds.txt file
    check_db_shares()
    entries = fetch_builds()
    dbox_shared = get_shared_links_db()
    repaired = 0
    for k, v in entries.items():
        try: build_name = v['filename']
        except: print(f'{k} Missing Filename!')
        print(build_name)
        build_url = v['url']
        print(build_url)
        for name, values in dbox_shared.items():
            if name == build_name:
                url_dbox = dbox_shared[build_name]['url']
                dbox_url = f'"{url_dbox}"'
                if build_url != dbox_url:
                    change_build_entry(k, 'url', dbox_url, entries)
                    craft_build(entries)
                    print(f'Patching {k} Build URL from Dropbox.')
                    repaired += 1
                else:
                    pass
    if temp_exists:
        print(f'[WARNING] Check {localbuild} in Temp directory before upload.')
        upload_build_file()
    else: print('All Links Working Correctly!')

def url_from_dbox_option():
    dbox_shared = get_shared_links_db()
    name = choices_menu(dbox_shared)
    if name == 'C':
        return
    url = dbox_shared[name]['url']
    if url is None:
        return "Shared Link Does Not Exist"
    else:
        return url

def dbox_upload(local_path, remote_path):
    # local_path points to directory + filename
    # remote_path points to directory + filename
    if local_path is None:
        return "[ERROR] Missing local path"
    elif remote_path is None:
        return "[ERROR] Missing remote path"
    else:
        pass
    dbx = Dropbox(db_token, timeout=900)
    with open(local_path, "rb") as f:
        file_size = path.getsize(local_path)
        chunk_size = 12 * 1024 * 1024
        if file_size <= chunk_size:
            print(dbx.files_upload(f.read(), remote_path))
        else:
            with tqdm(total=file_size, desc='Uploading Build', miniters=-1, mininterval=1, bar_format='{l_bar}') as pbar:
                upload_session_start_result = dbx.files_upload_session_start(
                    f.read(chunk_size))
                pbar.update(chunk_size)
                cursor = files.UploadSessionCursor(
                    session_id=upload_session_start_result.session_id,
                    offset=f.tell(),)
                commit = files.CommitInfo(path=remote_path, mode=WriteMode('overwrite'))
                while f.tell() < file_size:
                    if (file_size - f.tell()) <= chunk_size:
                        dbx.files_upload_session_finish(f.read(chunk_size), cursor, commit)
                    else:
                        dbx.files_upload_session_append(
                            f.read(chunk_size),
                            cursor.session_id,
                            cursor.offset,)
                        cursor.offset = f.tell()
                    pbar.update(chunk_size)

def dbox_upload_router():
    choice = valid_yn('Create New Build Name? Y/N: ').upper()
    if choice == 'Y':
        name = input('Build Name: ')
        name = name.removeprefix('"').removesuffix('"')
        fname = (f'{name}.zip')
    else:
        fname = filename_from_dbox() # TODO
    clean_kodi()
    print('Starting Upload Process')
    tmp_build = path.join(temp_dir, fname[0])
    zip_kodi(tmp_build)
    print('Starting Dropbox Upload')
    dbox_upload(tmp_build, fname[1])
    print(f'{fname[0]} Uploaded Successfully!\n')
    remove(tmp_build)

def upload_build_file():
    try:
        transport = Transport(sftp_host, 22)
        transport.connect(username=sftp_username, password=sftp_password)
        sftp = SFTPClient.from_transport(transport)
        if sftp.put(temp_build, sftp_remotepath):
            sftp.close()
            transport.close()
            print(f"Successfuly Uploaded {localbuild}")
            delete_build_file()  # Only deletes build file on Success
        else:
            print(f"[ERROR] Failed To Upload {localbuild}")
    except FileNotFoundError as f:
        print(f"[ERROR] No {localbuild} in Temp Folder!")
        return

def delete_build_file():
    try:
        remove(temp_build)
    except FileNotFoundError as f:
        print("[ERROR] No Temp Build File!")

def delete_dbox_file():
    dbx = Dropbox(db_token, timeout=900)
    response = dbx.files_list_folder(sftp_remotebuilds)
    paths = []
    for i in response.entries:
        paths.append(i.path_display)
    print(f'Select Dropbox File to Delete')
    print('~' * 25)
    for idx, item in enumerate(paths):
        idx += 1
        item = item.rsplit('/')[2]
        print(f'{idx}. {item}')
    print('~' * 25)
    option = valid_choice('Delete: ', idx)
    for idx, items in enumerate(paths):
        if option == idx + 1:
            path = items
    print(f'[WARNING] Removing {item}')
    dbx.files_delete_v2(path)
    print(f'[DONE] Removed Successfully: {item}')

def create_new_build_entry():
    def return_default_on_empty(msg):
        choice = input(msg)
        if len(choice.strip()) <= 0:
            return '"http://"'
        else:
            return f'"{choice}"'

    print('Beginning Build Creator\n')
    choice = valid_yn('[WARNING] Must Upload Remote File First! Continue? Y/N: ').upper()
    if choice == 'N':
        return
    else:
        entries = fetch_builds()
    print('[WARNING] Nothing is Final Until Build File is Uploaded.')
    print('[WARNING] When pasting, make sure not to include the quotes!\n')
    name = f'"{input("Build Name: ").title()}"'
    version = f'"{input("Version: ")}"'
    print('Point to filename:')
    filename = filename_from_dbox()[1]
    url = f'"{create_share_link(filename, show=False)}"'
    print(f'Share Link Created for {name}: {url}')
    print(f'Pointing {name} to {filename}')
    icon = return_default_on_empty("[Press Enter To Skip] Paste Icon URL: ")
    fanart = return_default_on_empty("[Press Enter To Skip] Paste Fanart URL: ")
    description = f'"{input("Please Enter Description: ")}"'.title()
    entries[name] = {'version': version, 'url': url,'filename': filename, 'minor': '"http://"', 'gui': '"http://"', 'kodi': '"19.0"', 'theme': '"http://"', 
                     'icon': icon, 'fanart': fanart, 'preview': '"http://"', 'adult': '"no"', 'info': '"http://"', 'description': description}
    pver = version.removeprefix('"').removesuffix('"')
    print(f'[DONE] {name} Added Successfully with Version: {pver}')
    print('Adding Build Entry')
    craft_build(entries)

def remove_build():  # works with local %temp%/build.txt
    entries = fetch_builds()
    name = return_option_from_builds(show=False)[0]
    del entries[name]
    craft_build(entries)
    build = name.removeprefix('"').removesuffix('"')
    print(f'[DONE] Removed Successfully: {build}')

def craft_build(entries: dict) -> None:
    if entries is None or len(entries) == 0:
        print("No Entries Found. No File Possibly?")
    else:
        write_list = []
        for e, v in entries.items():
            name = f'\nname={e}\n'
            write_list.append(name)
            for d, t in v.items():
                entry = f'{d}={t}\n'
                write_list.append(entry)
        for item in write_list:
            if "filename=" in item:
                write_list.pop(write_list.index(item))
        with open(temp_build, 'w') as f:
            f.writelines(write_list)
        option = valid_yn(f"Upload Modified {localbuild}? y/n: ")
        if option == 'Y':
            upload_build_file()
        else:
            return

def builds_qty(): # returns int
    return len(fetch_builds())

def clean_cache():
        dbfiles = ['cache.db', 'meta.db', 'meta.5.db', 'cache.providers.13.db', 
                   'torrentScrape.db', 'simplecache.db', 'metadata.db', 'search.db',
                   'traktSync.db', 'cache.v', 'fanarttv.db', 'cache.sqlite']
        db_loc = path.join(userdata_path, 'addon_data')
        for root, dirs, files in walk(db_loc):
            for f in files:
                if f in dbfiles:
                    file = path.join(root, f)
                    print(f'-- Removing DB: {file}')
                    unlink(file)

def clean_thumbs(msg=None):
        if msg is not None: print(msg)
        try: rmtree(thumb_dir) 
        except FileNotFoundError as nf: pass

def clean_dbs():
        print('\n[WARNING] This will remove these Databases:')
        print('[WARNING] TV*.db, Textures*.db, Epg*.db')
        print('[WARNING] Please make backups before running!') # TODO
        run = valid_yn("\nWould you like to continue? Y/N: ").upper()
        if run == 'Y':
            print('\n- Removing Extra Databases')
            includes = ['Textures', 'TV', 'Epg']
            for dirpath, dirnames, filenames in walk(dbase):
                for files in filenames:
                    if files.startswith(tuple(includes)):
                        remove(path.join(dirpath, files))
                        print(f'-- Removing {files} Database')
            clean_thumbs()
        else:
            return

def return_settings_paths():
    # returns all filepaths with 'settings.xml'
    settings_paths = []
    for root, dirs, files in walk(addn_data):
        for f in files:
            if 'settings.xml' in f:
                settings_paths.append(path.join(root, f))
    return settings_paths

def return_auth_tokens(use='all'):
    # returns tokens to use for clearing auths
    debrid_tokens = ['rd.username', 'rd.premiumstatus', 'rd.auth', 'rd.refresh', 
                     'rd.client_id', 'realdebrid.client_id', 'realdebrid.refresh',
                     'rd.expiry', 'rd.secret', 'realdebrid.token', 'realdebrid.username', 
                     'realdebrid.secret', 'alldebrid.token', 'alldebrid.username', 
                     'premiumize.token', 'premiumize.username']

    trakt_tokens = ['trakt.token', 'trakt.username', 'trakt.refresh', 'trakt.authtrakt', 
                    'trakt.clientid', 'trakt.secret', 'trakt.auth', 'trakt.isauthed']

    api_tokens = ['tvdb.api.key', 'fanart.tv.api.key', 'tmdb.api.key', 'tmdb.username', 
                  'tmdb.password', 'tmdb.session_id', 'imdb.user', 'tvdb.jw', 'tvdb.expiry', 
                  'furk.username', 'furk.password', 'furk.api.key', 'easynews.username', 
                  'easynews.password', 'gdrive.cloudflare_url', 'ororo.email', 'ororo.password',
                  'filepursuit.api.key', 'fanart.apikey', 'omdb.apikey', 'tvdb.apikey',
                  'tmdb.apikey']

    all_tokens = debrid_tokens + trakt_tokens

    if use == 'all':
        return all_tokens
    elif use == 'debrid':
        return debrid_tokens
    elif use == 'trakt':
        return trakt_tokens
    elif use == 'api':
        return api_tokens
    else:
        return 'Must define whether to use trakt, debrid, or all'

def auth_scrub(settings_paths, tokens):
    # clears auths using tokens, in settings_paths
    print('\n[STARTED] Scrubbing Auths')
    if is_running:
        kill_kodi()
    
    for path in settings_paths:
        tree = ET.parse(path)
        root = tree.getroot()
        for elm in root.iter('setting'):
            id = elm.attrib['id']
            value = elm.text
            if id in tokens:
                if value is not None:
                    elm.text = None
                    elm.attrib = {"id": id, "default": "true"}
                    print(elm.attrib, value)
                    #tree.write(path)
    print('- Cleaning Caches')
    clean_cache()
    print('- Cleaning Thumbnails')
    clean_thumbs()
    print('[DONE] Scrub Complete')

def clean_db_router(clean: str) -> None:
    if clean is not None:
        if is_running: 
            kill_kodi()
    else:
        return

    def clean_resolvers():
        pass

    if clean == 'all':
        clean_cache()
        clean_thumbs()
        clean_dbs()
        clean_resolvers()
    elif clean == 'cache':
        clean_cache()
    elif clean == 'thumbnails':
        clean_thumbs('Cleaning Thumbnails')
    elif clean == 'databases':
        clean_dbs()
    elif clean == 'resolvers':
        clean_resolvers()
    else:
        return "[ERROR] No Option Selected"
    return

def dbox_menu():
    while True:
        print()
        print('~' * 25)
        print('  Dropbox Menu  ')
        print('~' * 25)
        print('1. Delete Remote Build')
        print('2. Go Back')
        print('~' * 25)
        choice = valid_choice('Option: ', 2)
        if choice == 1:
            delete_dbox_file()
        else:
            print('\nExiting KButler.\n')
            break

def adv_settings():
    pass

def db_purge_menu():
    while True:
        print()
        print('~' * 25)
        print('  Database Menu  ')
        print('~' * 25)
        print('1. Clean All')
        print('2. Clean Cache')
        print('3. Clean Thumbnails')
        print('4. Clean Databases')
        print('5. Clean Resolvers')
        print('6. Go Back')
        print('~' * 25)
        choice = valid_choice('Option: ', 6)
        if choice == 1:
            clean_db_router('all')
        elif choice == 2:
            clean_db_router('cache')
        elif choice == 3:
            clean_db_router('thumbnails')
        elif choice == 4:
            clean_db_router('databases')
        elif choice == 5:
            clean_db_router('resolvers')
        else:
            print('\nExiting KButler.\n')
            break

def purge_auths():
    while True:
        print()
        print('~' * 25)
        print('  Auths Menu  ')
        print('~' * 25)
        print('1. Purge All Auths')
        print('2. Clear Trakt')
        print('3. Clear Debrid')
        print('4. Go Back')
        print('~' * 25)
        choice = valid_choice('Option: ', 4)
        if choice == 1:
            settings_paths = return_settings_paths()
            tokens = return_auth_tokens(use='all')
            auth_scrub(settings_paths, tokens)
        elif choice == 2:
            settings_paths = return_settings_paths()
            tokens = return_auth_tokens(use='trakt')
            auth_scrub(settings_paths, tokens)
        elif choice == 3:
            settings_paths = return_settings_paths()
            tokens = return_auth_tokens(use='debrid')
            auth_scrub(settings_paths, tokens)
        else:
            print('\nExiting KButler.\n')
            break

def kodi_maint():
    while True:
        print()
        print('~' * 25)
        print('  Kodi Maintenance  ')
        print('~' * 25)
        print('1. Database Menu')
        print('2. Auths Menu')
        print('3. Advanced Settings')
        print('4. Go Back')
        print('~' * 25)
        choice = valid_choice('Option: ', 4)
        if choice == 1:
            db_purge_menu()
        elif choice == 2:
            purge_auths()
        elif choice == 3:
            adv_settings()
        else:
            print('\nExiting KButler.\n')
            break

def configure_build():
    while True:
        print()
        print('~' * 25)
        print(f'  Configure {localbuild}  ')
        print('~' * 25)
        print('1. Add New Build') # TODO
        print('2. Remove Build')
        print('3. Show Builds')
        print('4. Quick Edit')
        print('5. Repair Links')
        print('6. Upload Changes')
        print('7. Discard Changes')
        print('8. Go Back')
        print('~' * 25)
        choice = valid_choice('Option: ', 8)
        if choice == 1:
            create_new_build_entry()
        elif choice == 2:
            remove_build()
        elif choice == 3:
            print("\nCurrent Builds:")
            fetch_urls(show=True)
        elif choice == 4:
            change_entry()
        elif choice == 5:
            automate_shared_links()
        elif choice == 6:
            upload_build_file()
        elif choice == 7:
            delete_build_file()
        else:
            print('\nExiting KButler.\n')
            break

def main():
    while True:
        print('~' * 25)
        print(f'  Kodi Butler v{VERSION}  ')
        print('~' * 25)
        print('1. Clean Kodi Files')
        print('2. Upload Build Zip')
        print('3. Configure Builds')
        print('4. Kodi Maintenance')
        print('5. Dropbox Menu')
        print('6. Fresh Install')
        print('7. Exit')
        print('~' * 25)
        choice = valid_choice('Option: ', 7)
        if choice == 1:
            clean_kodi()
        elif choice == 2:
            dbox_upload_router()
        elif choice == 3:
            configure_build()
        elif choice == 4:
            kodi_maint()
        elif choice == 5:
            dbox_menu()
        elif choice == 6:
            fresh_install()
        else:
            break

if __name__=='__main__':
    installed = path.isdir(path.expandvars('%appdata%\Kodi'))
    if installed:
        try:
            main()
        except KeyboardInterrupt as ki:
            print('\nExiting KButler.\n') 
            exit()
    else:
        print('[ERROR] Kodi Not Installed. Exiting.')
        exit()