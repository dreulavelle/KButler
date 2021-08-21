from os import path, environ, chdir, listdir, remove, walk
from re import sub
from time import sleep
from psutil import process_iter
from shutil import rmtree
from zipfile import ZIP_DEFLATED, ZipFile
from paramiko import Transport, SFTPClient
from dropbox import Dropbox, exceptions, files
from dropbox.files import UploadSessionCursor, CommitInfo, WriteMode
from dropbox.exceptions import ApiError, AuthError
from bs4 import BeautifulSoup
from requests import get
from tqdm import tqdm
from configparser import ConfigParser
import xml.etree.ElementTree as ET

VERSION = '0.6.7'

try: # Set Variables. [WARNING] ONLY change if you know what you're doing!
    config = ConfigParser()
    config.read('config.ini')
    kodipath = path.expandvars('%appdata%\Kodi\\')
    user = path.expandvars('%userprofile%')
    userdata_path = path.expandvars('%appdata%\Kodi\\userdata\\')
    addons_path = path.expandvars('%appdata%\Kodi\\addons\\')
    desktop = path.expandvars('%userprofile%\Desktop\\')
    retain_base = ['addons', 'userdata'] # can be cleaned up # TODO
    remove_addons = ['packages', 'temp'] # can be cleaned up # TODO
    remove_userdata = ['Thumbnails', 'Savestates', 'playlists'] # can be cleaned up # TODO
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
    temp_dir = environ.get('TEMP')
    temp_build = path.join(temp_dir + "\\builds.txt")
    dbase = path.join(userdata_path + "\\Database")
    thumb_dir = path.join(userdata_path + "\\Thumbnails")
except: 
    print('[ERROR] config.ini File Missing. Exiting!')
    print('You can get an example config.ini at:')
    print('###  https://github.com/dreulavelle/KButler/blob/KButler/config_example.ini')
    print('Save this to the same directory as this program and rename to config.ini')
    print('[WARNING] Make sure to edit the values! Then you should be all set!')
    exit()

if path.isfile(temp_build):
    temp_exists = True
else:
    temp_exists = False

is_running = "kodi.exe" in (p.name() for p in process_iter())

def valid_choice(msg, exit_opt=10): # returns an integer
    while True:
        try:
            num = int(input(msg))
            if num > exit_opt or num == 0 or num < 0:
                print(f'Please choose between 1 and {exit_opt}.')
            elif num < exit_opt:
                return num
            elif num == exit_opt:
                return exit_opt
            else:
                raise ValueError
        except ValueError:
            print(f'Please choose between 1 and {exit_opt}.')

def valid_yn(msg): # returns 'Y' or 'N'
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

def clean_kodi():
    print('- Base Files')
    chdir(kodipath)
    for item in listdir(kodipath):
        if item not in retain_base:
            try:
                remove(item)
            except:
                rmtree(kodipath + item)
    print('- Addons Path Files')
    chdir(addons_path)
    for item in listdir(addons_path):
        if item in remove_addons:
            rmtree(addons_path + item)
    print('- Userdata Path Files')
    chdir(userdata_path)
    for item in listdir(userdata_path):
        if item in remove_userdata:
            rmtree(userdata_path + item)
    chdir(desktop)
    print('Cleaning Done\n')

# def clean_kodi():
#     exclusions = ['addons', 'media', 'userdata', 'kodi.']
#     for root, dirs, files in walk(kodipath):
#         file_count = 0
#         file_count += len(files)
#         if file_count > 0:            
#             for f in files:
#                 if not any(e in f for e in exclusions):
#                     unlink(path.join(root, f))
#                 else:
#                     print(f"purgeHome Excluding '{f}'.")
#             for d in dirs:
#                 if not any(e in d for e in exclusions):
#                     rmtree(path.join(root, d))
#                 else:
#                     print(f"purgeHome Excluding '{d}'.")
#         break

def zip_kodi(zipname_path=None):
    if zipname_path is None or path.isdir(zipname_path):
        print("No File Given to Zip. Closing.")
        return
    print(f"Zipping Kodi in: {zipname_path}")
    length = len(kodipath)
    with ZipFile(zipname_path, 'w', allowZip64=True, compression=ZIP_DEFLATED) as zip:
        for root, dirs, files in walk(kodipath):
            folder = root[length:] # path without "parent"
            for file in files:
                zip.write(path.join(root, file), path.join(folder, file))
    name = path.basename(zipname_path)
    print(f'{name} Build Created!')

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

def fetch_urls(show=False):
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
    print('\nSelect Key To Change')
    print('~' * 25)
    for idx, item in enumerate(choices):
        idx += 1
        print(f'{idx}. {item}')
    print('~' * 25)
    option = valid_choice('Key: ', idx)
    for idx, items in enumerate(choices):
        if option == idx + 1:
            key = items
    return key

def return_option_from_builds(show=False):
    # using remote builds.txt file
    # returns: index, name, version, url, description
    print('\nPlease Select an Item')
    print('~' * 25)
    builds = fetch_builds()
    for idx, item in enumerate(builds):
        idx += 1
        print(f'{idx}. {item}')
    print('~' * 25)
    option = valid_choice('Option: ', idx)
    for idx, items in enumerate(builds):
        if option == idx + 1:
            name = items
    index = option - 1
    version = builds[name]['version']
    url = builds[name]['url']
    description = builds[name]['description']
    if show:
        stripped = name.removeprefix('"').removesuffix('"')
        print(f'Build: {stripped}\nCurrent Version: {version}\nURL: {url}')
    return index, name, version, url, description

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

def change_build_entry(name=None, key=None, value=None, entries=None):
    # name = "name" in builds.txt (with quotes)
    # key = key to change
    # value = value to change
    # entries = builds.txt dict
    if name is None or key is None or value is None or entries is None:
        return
    values = entries[name]
    if key in values:
        values[key] = value
        entries = values
    else:
        return

def change_entry():
    entries = fetch_builds()
    dname = return_option_from_builds()[1]
    key = return_key_to_change()
    value = input("Change To: ")
    change = f'"{value}"'
    change_build_entry(dname, key, change, entries)
    craft_build(entries)

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

def create_share_link(remote_filepath, show=False):
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
            try: create_share_link(path) # create urls if none exists
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
    print('\nSelect Dropbox File')
    print('~' * 25)
    dbox_shared = get_shared_links_db()
    for idx, item in enumerate(dbox_shared):
        idx += 1
        print(f'{idx}. {item}')
    print('~' * 25)
    option = valid_choice('Option: ', idx)
    for idx, items in enumerate(dbox_shared):
        if option == idx + 1:
            name = items
    url = dbox_shared[name]['url']
    if url == None:
        return "Shared Link Does Not Exist"
    else:
        return url

def dbox_upload(local_path, remote_path):
    # local_path points to directory + filename
    # remote_path points to directory + filename
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
    print('Starting Upload Process')
    tmp_build = path.join(f'{temp_dir}' + f'\\{fname}')
    if path.exists(tmp_build):
        remove(tmp_build)
    print('Zipping Kodi For Upload')
    zip_kodi(tmp_build)
    rloc = (f'{sftp_remotebuilds}{fname}')
    print('Starting Dropbox Upload')
    dbox_upload(tmp_build, rloc)
    print(f'{fname} Uploaded Successfully!')
    print(f'Removing: {tmp_build}')
    remove(tmp_build)
    print('Upload Complete.\n')

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
    url = f'"{create_share_link(filename)}"'
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
    name = return_option_from_builds()[1]
    del entries[name]
    craft_build(entries)
    build = name.removeprefix('"').removesuffix('"')
    print(f'[DONE] Removed Successfully: {build}')

def craft_build(entries):
    if len(entries) > 0:
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
    else:
        print("No Entries Found. No File Possibly?")

def builds_qty(): # returns int
    return len(fetch_builds())

def clean_databases():
    print('\n[WARNING] This will remove these Databases:')
    print('[WARNING] TV*.db, Textures*.db, Epg*.db, MyMusic*.db, MyVideos*.db')
    print('[WARNING] Please make backups before running!') # TODO
    run = valid_yn("\nWould you like to continue? Y/N: ").upper()
    if run == 'Y':
        print('\nCleaning Databases')
        if is_running: 
            kill_kodi()
        includes = ['TV', 'Textures', 'Epg', 'MyMusic', 'MyVideos']
        for dirpath, dirnames, filenames in walk(dbase):
            for files in filenames:
                if files.startswith(tuple(includes)):
                    remove(path.join(dirpath, files))
                    print(f'- Removing {files} Database')
        print('Cleaning Thumbnails\n')
        try: rmtree(thumb_dir) 
        except FileNotFoundError as nf: pass
    else:
        return

def adv_settings():
    pass

def purge_kodi():
    while True:
        print()
        print('~' * 25)
        print('  Kodi Clean-Up  ')
        print('~' * 25)
        print('1. Clean All')
        print('2. Clean Cache')
        print('3. Clean Packages')
        print('4. Clean Thumbnails')
        print('5. Clean Databases')
        print('6. Clean Resolvers')
        print('7. Exit')
        print('~' * 25)
        choice = valid_choice('Option: ', 7)
        if choice == 1:
            pass
        elif choice == 2:
            pass
        elif choice == 3:
            pass
        elif choice == 4:
            pass
        elif choice == 5:
            clean_databases()
        elif choice == 6:
            pass
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
            pass
        elif choice == 2:
            pass
        elif choice == 3:
            pass
        else:
            print('\nExiting KButler.\n')
            break

def kodi_maint():
    while True:
        print()
        print('~' * 25)
        print('  Kodi Maintenance  ')
        print('~' * 25)
        print('1. Purge Menu')
        print('2. Auths Menu')
        print('3. Advanced Settings')
        print('4. Go Back')
        print('~' * 25)
        choice = valid_choice('Option: ', 4)
        if choice == 1:
            purge_kodi()
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
        elif choice == 6:
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
        print('5. Exit')
        print('~' * 25)
        choice = valid_choice('Option: ', 5)
        if choice == 1:
            print('\nCleaning Process Started')
            print('- Checking Kodi Process')
            if is_running:
                kill_kodi()
            print('- Cleaning Kodi Folder')
            clean_kodi()
        elif choice == 2:
            dbox_upload_router()
        elif choice == 3:
            configure_build()
        elif choice == 4:
            kodi_maint()
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