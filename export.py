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
for d in [BUILD_DIR, DIST_DIR, PROJECT_DIR, ]:
    if os.path.isdir(d):
        logger.info('Deleting folder {}...'.format(d))
        shutil.rmtree(d)
ZIP_FILE = PROJECT_DIR + '.zip'
if os.path.isfile(ZIP_FILE):
    logger.info('Deleting archive {}...'.format(ZIP_FILE))
    os.unlink(ZIP_FILE)
exe_file = basename + '.exe'
pyinstaller_params = [
    '--clean',
    '--noconfirm',
    '--name=' + basename,
    '--onefile',
    '--hiddenimport=web',
    '--paths=.',
    'papi_web.py',
]
run(pyinstaller_params)
logger.info('Creating folder {} from {}...'.format(PROJECT_DIR, DATA_DIR))
shutil.copytree(DATA_DIR, PROJECT_DIR)
dist_exe_file = os.path.join(DIST_DIR, exe_file)
logger.info('Moving {} to {}...'.format(dist_exe_file, PROJECT_DIR))
shutil.move(dist_exe_file, PROJECT_DIR)
target_dir = os.path.join(PROJECT_DIR, CUSTOM_DIR)
logger.info('Copying {} to {}...'.format(CUSTOM_DIR, target_dir))
shutil.copytree(CUSTOM_DIR, target_dir)
target_file = os.path.join(PROJECT_DIR, 'server.bat')
logger.info('Creating batch file {}...'.format(target_file))
with open(target_file, 'wt') as f:
    f.write('@echo off'
            '@rem Papi-web {} - {} - {}'
            '{} --server'.format(exe_file, PAPI_WEB_COPYRIGHT, PAPI_WEB_URL, PAPI_WEB_VERSION))
target_file = os.path.join(PROJECT_DIR, 'ffe.bat')
logger.info('Creating batch file {}...'.format(target_file))
with open(target_file, 'wt') as f:
    f.write('@echo off'
            '@rem Papi-web {} - {} - {}'
            '{} --ffe'.format(exe_file, PAPI_WEB_COPYRIGHT, PAPI_WEB_URL, PAPI_WEB_VERSION))

logger.info('Creating archive {}...'.format(ZIP_FILE))
with ZipFile(ZIP_FILE, 'w') as zip_file:
    os.chdir(PROJECT_DIR)
    for folder_name, sub_folders, file_names in os.walk('.'):
        zip_file.write(folder_name, folder_name)
    for folder_name, sub_folders, file_names in os.walk('.'):
        for filename in file_names:
            file_path = os.path.join(folder_name, filename)
            zip_file.write(file_path, file_path)

os.chdir(os.path.dirname(os.path.realpath(__file__)))

logger.info('Deleting folder {}...'.format(PROJECT_DIR))
shutil.rmtree(PROJECT_DIR)
for d in [BUILD_DIR, DIST_DIR, ]:
    if os.path.isdir(d):
        logger.info('Deleting folder {}...'.format(d))
        shutil.rmtree(d)
spec_file: str = basename + '.spec'
logger.info('Deleting spec file {}...'.format(spec_file))
os.unlink(spec_file)

TEST_DIR = os.path.join('..', 'test')
logger.info('Creating test environment in {}...'.format(TEST_DIR))
if not os.path.isdir(TEST_DIR):
    os.makedirs(TEST_DIR)
with ZipFile(ZIP_FILE, 'r') as zip_file:
    zip_file.extractall(TEST_DIR)
