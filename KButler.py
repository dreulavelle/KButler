import os
from re import sub
from shutil import rmtree
from signal import SIGTERM
from time import sleep
from zipfile import ZIP_DEFLATED, ZipFile

# Must Have These Installed
import dropbox, paramiko
from bs4 import BeautifulSoup
from requests import get
from tqdm import tqdm
from wmi import WMI

# To get started: pip install dropbox requests zipfile BeautifulSoup4 tqdm

# Point to Dropbox Access Key Token. Ex: 'key'
access_token = os.environ.get('dbkey')

# Point to URL of build.txt. Ex: 'http://example.com/build.txt'
build_txt = os.environ.get('matrixbuilds')

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
    c = WMI()
    for process in c.Win32_Process():
        if 'kodi' in process.Name:
            print("- Killing Kodi Process")
            x = os.kill(process.ProcessId, SIGTERM)
        else:
            pass
    sleep(3)

def clean_kodi():
    kodipath = os.path.expandvars('%appdata%\Kodi\\')
    userdata_path = os.path.expandvars('%appdata%\Kodi\\userdata\\')
    addons_path = os.path.expandvars('%appdata%\Kodi\\addons\\')
    desktop = os.path.expandvars('%userprofile%\Desktop\\')
    retain_base = ["addons", "userdata"]
    remove_addons = ["packages", "temp"]
    remove_userdata = ["Thumbnails", "Savestates", "playlists", "library"]

    print("- Base Files")
    os.chdir(kodipath)
    for item in os.listdir(kodipath):
        if item not in retain_base:
            try:
                os.remove(item)
            except:
                rmtree(kodipath + item)

    print("- Addons Path Files")
    os.chdir(addons_path)
    for item in os.listdir(addons_path):
        if item in remove_addons:
            rmtree(addons_path + item)

    print("- Userdata Path Files")
    os.chdir(userdata_path)
    for item in os.listdir(userdata_path):
        if item in remove_userdata:
            rmtree(userdata_path + item)
    
    os.chdir(desktop)
    print("Cleaning Done\n")

def zip_kodi(dirPath=None, zipFilePath=os.path.expandvars('%userprofile%\Desktop')):
    parentDir, dirToZip = os.path.split(dirPath)

    def trimPath(path):
        archivePath = path.replace(parentDir, "", 1)
        if parentDir:
            archivePath = archivePath.replace(os.path.sep, "", 1)
        archivePath = archivePath.replace(dirToZip + os.path.sep, "", 1)
        return os.path.normcase(archivePath)

    print("- Writing Files to Zip")
    with ZipFile(zipFilePath, "w",compression=ZIP_DEFLATED) as zip_file:
        for (archiveDirPath, dirNames, fileNames) in os.walk(dirPath):
            for fileName in fileNames:
                filePath = os.path.join(archiveDirPath, fileName)
                zip_file.write(filePath, trimPath(filePath))

    print('Kodi Build Created!')
    return zipFilePath

def get_builds(build_txt):
    builds = []
    with get(build_txt, stream=True) as r:
        soup = BeautifulSoup(r.content, 'lxml')
        data = soup.text.split('\n') 
        for line in data:
            cleaned = line.split('=')
            if 'name' in cleaned:
                string = line.strip().split('name=')[1]
                name = string.removeprefix('"').removesuffix('"')
                builds.append(name)
    return builds

def return_option_from_builds():
    print("\nPlease Select an Item")
    print("~" * 25)
    builds = get_builds(build_txt)
    for idx, item in enumerate(builds):
        idx += 1
        print(f"{idx}. {item}")
    print("~" * 25)
    option = valid_choice("Option: ", idx)
    for idx, items in enumerate(builds):
        if option == idx + 1:
            return items

def prep_kodi():
    print("\nPrepping Kodi Build")
    print("- Checking Kodi Process")
    kill_kodi()
    print("- Cleaning Kodi Folder")
    clean_kodi()

def upload_build(access_token, file_from, file_to, timeout=900, chunk_size=4 * 1024 * 1024):
    kodipath = os.path.expandvars('%appdata%\Kodi')
    user = os.path.expandvars('%userprofile%')
    zipfilename = os.path.join(user, 'Desktop', file_from)
    print("\nCreating Kodi Build")
    zip_kodi(kodipath, zipFilePath=zipfilename)
    desktop = os.path.expandvars('%userprofile%\Desktop\\')
    os.chdir(desktop)
    file_size = os.path.getsize(file_from)
    chunk_size = 4 * 1024 * 1024
    dbx = dropbox.Dropbox(access_token, timeout=timeout)
    try:
        dbx.files_delete_v2(file_to)    # Tries to upload files less than 150mb.
    except dropbox.exceptions.ApiError: 
        pass                            # Else, continues to open session to upload larger files.
    with open(file_from, "rb") as f:
        file_size = os.path.getsize(file_from)
        chunk_size = 4 * 1024 * 1024
        if file_size <= chunk_size:
            dbx.files_upload(f.read(), file_to)
        else:
            with tqdm(total=file_size, desc="Uploading Build", miniters=-1, mininterval=1, bar_format='{l_bar}') as pbar:
                upload_session_start_result = dbx.files_upload_session_start(f.read(chunk_size))
                pbar.update(chunk_size)
                cursor = dropbox.files.UploadSessionCursor(
                    session_id=upload_session_start_result.session_id,
                    offset=f.tell())
                commit = dropbox.files.CommitInfo(path=file_to)
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

    link = dbx.sharing_create_shared_link(file_to)
    url = link.url
    dl_url = sub(r"\?dl\=0", "?dl=1", url)
    print("Removing Local Zip File")
    os.remove(file_from)
    return dl_url

def get_db_files():
    dbx = dropbox.Dropbox(access_token, timeout=900)
    entries = dbx.files_list_folder('').entries
    file_list = []
    for entry in entries:
        file_list.append(entry.name)
    return file_list

def compare_db_builds():  # TODO
    dbox = get_db_files()
    builds = get_builds(build_txt)
    for entries in dbox:
        if entries not in builds:
            print(entries)
        else:
            print("All Set!")
    print()
    print(f"Dropbox: {dbox}")
    print(f"Builds: {builds}")

def dl_builds_file():
    # /home/spoked/spoked.xyz/repo
    


def main():
    while True:
        try:
            print("~" * 25)
            print("  Kodi Butler V0.9.4  ")
            print("~" * 25)
            print("1. Prep Kodi")
            print("2. Upload Build")
            print("3. Exit")
            print("~" * 25)
            choice = valid_choice("Option: ", 3)
            if choice == 1:
                prep_kodi()
            elif choice == 2:
                choice = valid_yn("Create New Build Name? Y/N: ").upper()
                if choice == 'Y':
                    name = input("Build Name: ")
                else:
                    name = return_option_from_builds()
                fname = (f'{name}.zip')
                floc = (f'/{name}.zip')
                url = upload_build(access_token, fname, floc)
                print(f'\nDone! URL: {url}\n')   # Print downloadable URL
            else:
                print("Exiting Program.\n")
                break
        except KeyboardInterrupt:
            print("\nExiting Program.\n") 
            break

if __name__=='__main__':
    installed = os.path.isdir(os.path.expandvars('%appdata%\Kodi'))
    if installed:
        compare_db_builds()
    else:
        print("Kodi Not Installed. Exiting.")
        exit
