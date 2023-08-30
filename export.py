import os
import shutil
from zipfile import ZipFile
from logging import Logger
from PyInstaller.__main__ import run
from common.papi_web_config import PAPI_WEB_VERSION, PAPI_WEB_COPYRIGHT, PAPI_WEB_URL
from common.logger import get_logger

logger: Logger = get_logger()

os.chdir(os.path.dirname(os.path.realpath(__file__)))

BUILD_DIR = 'build'
DIST_DIR = 'dist'
DATA_DIR = 'export-data'
CUSTOM_DIR = 'custom'
basename: str = 'papi-web-{}'.format(PAPI_WEB_VERSION)
EXPORT_DIR = os.path.join('..', 'export')
PROJECT_DIR = os.path.join(EXPORT_DIR, basename)
ZIP_FILE = PROJECT_DIR + '.zip'
EXE_FILE = basename + '.exe'
SPEC_FILE: str = basename + '.spec'
TEST_DIR = os.path.join('..', 'test')


def clean(clean_zip: bool):
    os.chdir(os.path.dirname(os.path.realpath(__file__)))
    for d in [BUILD_DIR, DIST_DIR, PROJECT_DIR, ]:
        if os.path.isdir(d):
            logger.info('Deleting folder {}...'.format(d))
            shutil.rmtree(d)
    if os.path.isfile(SPEC_FILE):
        logger.info('Deleting file {}...'.format(SPEC_FILE))
        os.unlink(SPEC_FILE)
    if clean_zip:
        if os.path.isfile(ZIP_FILE):
            logger.info('Deleting file {}...'.format(ZIP_FILE))
            os.unlink(ZIP_FILE)


def build_exe():
    os.chdir(os.path.dirname(os.path.realpath(__file__)))
    pyinstaller_params = [
        '--clean',
        '--noconfirm',
        '--name=' + basename,
        '--onefile',
        '--hiddenimport=common',
        '--hiddenimport=data',
        '--hiddenimport=database',
        '--hiddenimport=ffe',
        '--hiddenimport=web',
        '--paths=.',
        'papi_web.py',
    ]
    run(pyinstaller_params)


def create_project():
    os.chdir(os.path.dirname(os.path.realpath(__file__)))
    logger.info('Creating folder {} from {}...'.format(PROJECT_DIR, DATA_DIR))
    shutil.copytree(DATA_DIR, PROJECT_DIR)
    dist_exe_file = os.path.join(DIST_DIR, EXE_FILE)
    logger.info('Moving {} to {}...'.format(dist_exe_file, PROJECT_DIR))
    shutil.move(dist_exe_file, PROJECT_DIR)
    target_dir = os.path.join(PROJECT_DIR, CUSTOM_DIR)
    logger.info('Copying {} to {}...'.format(CUSTOM_DIR, target_dir))
    shutil.copytree(CUSTOM_DIR, target_dir)
    target_file = os.path.join(PROJECT_DIR, 'server.bat')
    logger.info('Creating batch file {}...'.format(target_file))
    with open(target_file, 'wt') as f:
        f.write('@echo off\n'
                '@rem Papi-web {} - {} - {}\n'
                '{} --server\n'.format(PAPI_WEB_VERSION, PAPI_WEB_COPYRIGHT, PAPI_WEB_URL, EXE_FILE))
    target_file = os.path.join(PROJECT_DIR, 'ffe.bat')
    logger.info('Creating batch file {}...'.format(target_file))
    with open(target_file, 'wt') as f:
        f.write('@echo off\n'
                '@rem Papi-web {} - {} - {}\n'
                '{} --ffe\n'.format(PAPI_WEB_VERSION, PAPI_WEB_COPYRIGHT, PAPI_WEB_URL, EXE_FILE))


def create_zip():
    logger.info('Creating archive {}...'.format(ZIP_FILE))
    with ZipFile(ZIP_FILE, 'w') as zip_file:
        os.chdir(PROJECT_DIR)
        for folder_name, sub_folders, file_names in os.walk('.'):
            zip_file.write(folder_name, folder_name)
        for folder_name, sub_folders, file_names in os.walk('.'):
            for filename in file_names:
                file_path = os.path.join(folder_name, filename)
                zip_file.write(file_path, file_path)


def build_test():
    os.chdir(os.path.dirname(os.path.realpath(__file__)))
    if not os.path.isdir(TEST_DIR):
        logger.info('Creating test environment in {}...'.format(TEST_DIR))
        os.makedirs(TEST_DIR)
    else:
        logger.info('Updating test environment in {}...'.format(TEST_DIR))
    with ZipFile(ZIP_FILE, 'r') as zip_file:
        zip_file.extractall(TEST_DIR)


def main():
    clean(clean_zip=True)
    build_exe()
    create_project()
    create_zip()
    build_test()
    clean(clean_zip=False)


main()
