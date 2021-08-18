from os import path, environ, chdir, listdir, kill, remove, walk
from re import sub
from shutil import rmtree
from signal import SIGTERM
from time import sleep
from zipfile import ZIP_DEFLATED, ZipFile
from paramiko import Transport, SFTPClient
from dropbox import Dropbox, exceptions, files
from bs4 import BeautifulSoup
from requests import get
from tqdm import tqdm
from wmi import WMI
from configparser import ConfigParser

try: # Set Variables. [WARNING] ONLY change if you know what you're doing!
    kb_version = '0.6.5'
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
    access_token = config['DROPBOX']['access_token']
    remote_builds = config['BUILDFILE']['remote_build_txt']
    localbuild = config['BUILDFILENAME']['localbuild']
    dropbox_host = config['SFTP']['dropbox_host']  
    dropbox_username = config['SFTP']['dropbox_username'] 
    dropbox_password = config['SFTP']['dropbox_password']
    dropbox_remotepath = config['SFTP']['dropbox_remotepath']
    dropbox_remotebuilds = config['SFTP']['dropbox_remotebuilds']
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

check = "kodi.exe" in (p.name() for p in psutil.process_iter())
if check:
    running = True
else:
    running = False

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
    c = WMI().Win32_Process()
    for process in c:
        if 'kodi' in process.Name:
            print('- Killing Kodi Process')
            kill(process.ProcessId, SIGTERM)
        else:
            pass
    sleep(3)

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
    length = len(kodipath)
    print(zipname_path)
    with ZipFile(zipname_path, 'w', allowZip64=True, compression=ZIP_DEFLATED) as zip:
        for root, dirs, files in walk(kodipath):
            folder = root[length:] # path without "parent"
            for file in files:
                zip.write(path.join(root, file), path.join(folder, file))
    name = path.basename(zipname_path)
    print(f'{name} Build Created!')

def fetch_builds():
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
    return entries

def fetch_urls():
    urls = []
    builds = fetch_builds()
    print("\nCurrent Builds:")
    for n, data in builds.items():
        version = data['version']
        url = data['url']
        print(f'{n} [{version}] URL: {url}')
        urls.append(url)
    return urls

def return_option_from_builds(show=False):
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
        print(f'\nBuild: {stripped}\nCurrent Version: {version}')
    return index, name, version, url, description

def dropbox_upload(file_from, file_to, timeout=900):
    # dropbox support. requires api key! (Free)
    zipfilename = path.join(temp_dir, file_from)
    print(zipfilename)
    print('\nCreating Kodi Build')
    print(kodipath)
    zip_kodi(zipname_path=zipfilename)
    chdir(temp_dir)
    file_size = path.getsize(file_from)
    chunk_size = 4 * 1024 * 1024
    dbx = Dropbox(access_token, timeout)
    try:
        dbx.files_delete_v2(file_to)    # Tries to upload files less than 150mb.
    except exceptions.ApiError: 
        pass                            # Else, continues to open session to upload larger files.
    with open(file_from, 'rb') as f:
        file_size = path.getsize(file_from)
        chunk_size = 4 * 1024 * 1024
        if file_size <= chunk_size:
            dbx.files_upload(f.read(), file_to)
        else:
            with tqdm(total=file_size, desc='Uploading Build', miniters=-1, mininterval=1, bar_format='{l_bar}') as pbar:
                upload_session_start_result = dbx.files_upload_session_start(f.read(chunk_size))
                pbar.update(chunk_size)
                cursor = files.UploadSessionCursor(
                    session_id=upload_session_start_result.session_id,
                    offset=f.tell())
                commit = files.CommitInfo(path=file_to)
                while f.tell() < file_size:
                    if (file_size - f.tell()) <= chunk_size:
                        dbx.files_upload_session_finish(f.read(chunk_size), cursor, commit)
                    else:
                        dbx.files_upload_session_append(
                            f.read(chunk_size),
                            cursor.session_id,
                            cursor.offset,
                        )
                        cursor.offset = f.tell()
                    pbar.update(chunk_size)

    if dbx.is_shared_link_already_exists(file_to):
        link = dbx.get_shared_link_already_exists(file_to)
    #link = dbx.get_shared_link_metadata(file_to)
    url = link.url
    dl_url = sub(r'\?dl\=0', '?dl=1', url)
    print('Removing Temp Zip File')
    remove(file_from)
    return dl_url      # <---- currently not working as intended. generates new share url when one already exists. #TODO

def upload_build_file():
    if temp_exists:
        transport = Transport((dropbox_host, 22))
        transport.connect(dropbox_username, dropbox_password)
        sftp = SFTPClient.from_transport(transport)
        if sftp.put(temp_build, dropbox_remotepath):
            sftp.close()
            transport.close()
            print("Successfuly Updated Builds")
        else:
            print("[ERROR] Failed To Upload File")
    else:
        print("[ERROR] No Temp Build File!")

def download_builds_file():
    resp = get(remote_builds)
    with open(temp_build, 'w') as f:
        f.write(resp.text)
    sleep(1)
    return

def delete_build_file():
    if temp_exists:
        remove(temp_build)
    else:
        print("[ERROR] No Temp Build File!")

def add_build():  # TODO
    if not temp_exists:
        download_builds_file()
    with open(temp_build, 'a') as f:
        name = (f'"{input("Build Name: ").title()}"')
        print(name) # for testing purposes
        version = input('Version: ')
        url = input('Paste URL: ')
        minor = "http://"
        gui = "http://"
        kodi = "19.0"
        theme = "http://"
        icon = input('Paste Icon URL: ').title()
        fanart = input('Paste Fanart URL: ')
        preview = "http://"
        adult = input('Adult content? yes/no: ').lower()
        info = "http://"
        description = input('Write a description: ')
        f.write(f'\n\nname="{name}"\nversion="{version}"') # TODO
    print(f'\nBuild {name} Added Successfully!')

def remove_build(entries=fetch_builds()):  # works with local temp/build.txt
    name = return_option_from_builds()[1]
    del entries[name]
    write_build(entries)
    build = name.removeprefix('"').removesuffix('"')
    print(f"Build {build} Removed Successfully!")

def write_build(entries):
    if len(entries) > 0:
        write_list = []
        for e, v in entries.items():
            name = f'\nname={e}\n'
            write_list.append(name)
            for d, t in v.items():
                entry = f'{d}={t}\n'
                write_list.append(entry)
        with open(temp_build, 'w') as f:
            f.writelines(write_list)
    else:
        print("No Entries Found. No File Possibly?")

def builds_qty():
    return len(fetch_builds())

def clean_databases():
    print('\n[WARNING] This will remove these Databases:')
    print('[WARNING] TV*.db, Textures*.db, Epg*.db, MyMusic*.db, MyVideos*.db')
    print('[WARNING] Please make backups before running!') # TODO
    run = valid_yn("\nWould you like to continue? Y/N: ").upper()
    if run == 'Y':
        print('\nCleaning Databases')
        if running: 
            kill_kodi()
        includes = ['TV', 'Textures', 'Epg', 'MyMusic', 'MyVideos']
        for dirpath, dirnames, filenames in walk(dbase):
            for files in filenames:
                if files.startswith(tuple(includes)):
                    remove(path.join(dirpath, files))
                    print(f'Removing {files} Database')
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
        print('1. Clean Cache')
        print('2. Clean Packages')
        print('3. Clean Thumbnails')
        print('4. Clean Databases')
        print('5. Clean Resolvers')
        print('6. Exit')
        print('~' * 25)
        choice = valid_choice('Option: ', 5)
        if choice == 1:
            pass
        elif choice == 2:
            pass
        elif choice == 3:
            pass
        elif choice == 4:
            clean_databases()
        elif choice == 5:
            pass
        else:
            print('\nExiting KButler.\n')
            break

def purge_auths():
    while True:
        print()
        print('~' * 25)
        print('  Purge Menu  ')
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
            pass
        elif choice == 2:
            purge_auths()
        elif choice == 3:
            adv_settings()
        else:
            print('\nExiting KButler.\n')
            break

def change_entry():
    while True:
        print()
        print('~' * 25)
        print('  Make Changes To Build  ')
        print('~' * 25)
        print('1. Change Name')
        print('2. Change Version')
        print('3. Change URL')
        print('4. Change Description')
        print('5. Go Back')
        print('~' * 25)
        choice = valid_choice('Option: ', 5)
        if choice == 1:
            pass
        elif choice == 2:
            pass
        elif choice == 3:
            pass
        elif choice == 4:
            pass
        else:
            print('\nExiting KButler.\n')
            break

def configure_build(): # TODO
    while True:
        print()
        print('~' * 25)
        print('  Configure Build  ')
        print('~' * 25)
        print('1. Add New Build')
        print('2. Remove Build')
        print('3. Show Builds Info')
        print('4. Change Entry')
        print('5. Upload Changes')
        print('6. Discard Changes')
        print('7. Go Back')
        print('~' * 25)
        choice = valid_choice('Option: ', 7)
        if choice == 1:
            add_build()
        elif choice == 2:
            remove_build()
        elif choice == 3:
            fetch_urls()
        elif choice == 4:
            change_entry()
        elif choice == 5:
            if upload_build_file():
                print("Successfuly Updated Builds")
            else:
                print("[ERROR] Failed To Update Builds!")
        elif choice == 6:
            delete_build_file()
        else:
            print('\nExiting KButler.\n')
            break

def main():
    while True:
        print('~' * 25)
        print(f'  Kodi Butler v{kb_version}  ')
        print('~' * 25)
        print('1. Clean Kodi Files')
        print('2. Upload Build')
        print('3. Configure Builds')
        print('4. Kodi Maintenance')
        print('5. Exit')
        print('~' * 25)
        choice = valid_choice('Option: ', 5)
        if choice == 1:
            print('\nPrepping Kodi Build')
            print('- Checking Kodi Process')
            kill_kodi()
            print('- Cleaning Kodi Folder')
            clean_kodi()
        elif choice == 2:
            choice = valid_yn('Create New Build Name? Y/N: ').upper()
            if choice == 'Y':
                name = input('Build Name: ')
            else:
                name = return_option_from_builds()[1]
            name = name.removeprefix('"').removesuffix('"')
            fname = (f'{name}.zip')
            floc = (f'/{name}.zip')
            url = dropbox_upload(fname, floc)
            print(f'\nDone! URL: {url}\n')   # Print downloadable URL
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
            #main()
            clean_databases()
        except KeyboardInterrupt as ki:
            print('\nExiting KButler.\n') 
            exit()
    else:
        print('[ERROR] Kodi Not Installed. Exiting.')
        exit()
