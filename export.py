import os
import shutil
from pathlib import Path
from zipfile import ZipFile
from logging import Logger
from PyInstaller.__main__ import run
from common.papi_web_config import PAPI_WEB_VERSION, PAPI_WEB_COPYRIGHT, PAPI_WEB_URL
from common.logger import get_logger

logger: Logger = get_logger()

BUILD_DIR: Path = Path('build')
DIST_DIR: Path = Path('dist')
DATA_DIR: Path = Path('export-data')
CUSTOM_DIR: Path = Path('custom')
basename: str = 'papi-web-{}'.format(PAPI_WEB_VERSION)
EXPORT_DIR: Path = Path('..', 'export')
PROJECT_DIR: Path = Path(EXPORT_DIR, basename)
ZIP_FILE: Path = Path(str(PROJECT_DIR) + '.zip')
EXE_FILENAME = basename + '.exe'
SPEC_FILE: Path = Path(basename + '.spec')
TEST_DIR: Path = Path('..', 'test')


def clean(clean_zip: bool):
    os.chdir(Path(__file__).resolve().parents[0])
    for d in [BUILD_DIR, DIST_DIR, PROJECT_DIR, ]:
        if Path(d).is_dir():
            logger.info('Deleting folder {}...'.format(d))
            shutil.rmtree(d)
    if SPEC_FILE.is_file():
        logger.info('Deleting file {}...'.format(SPEC_FILE))
        SPEC_FILE.unlink()
    if clean_zip:
        if ZIP_FILE.is_file():
            logger.info('Deleting file {}...'.format(ZIP_FILE))
            ZIP_FILE.unlink()


def build_exe():
    os.chdir(Path(__file__).resolve().parents[0])
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
    os.chdir(Path(__file__).resolve().parents[0])
    logger.info('Creating folder {} from {}...'.format(PROJECT_DIR, DATA_DIR))
    shutil.copytree(DATA_DIR, PROJECT_DIR)
    dist_exe_file: Path = Path(DIST_DIR, EXE_FILENAME)
    logger.info('Moving {} to {}...'.format(dist_exe_file, PROJECT_DIR))
    shutil.move(str(dist_exe_file), str(PROJECT_DIR))
    target_dir: Path = Path(PROJECT_DIR, CUSTOM_DIR)
    logger.info('Copying {} to {}...'.format(CUSTOM_DIR, target_dir))
    shutil.copytree(CUSTOM_DIR, target_dir)
    target_file: Path = Path(PROJECT_DIR, 'server.bat')
    logger.info('Creating batch file {}...'.format(target_file))
    with open(target_file, 'wt') as f:
        f.write('@echo off\n'
                '@rem Papi-web {} - {} - {}\n'
                '{} --server\n'.format(PAPI_WEB_VERSION, PAPI_WEB_COPYRIGHT, PAPI_WEB_URL, EXE_FILENAME))
    target_file = Path(PROJECT_DIR, 'ffe.bat')
    logger.info('Creating batch file {}...'.format(target_file))
    with open(target_file, 'wt') as f:
        f.write('@echo off\n'
                '@rem Papi-web {} - {} - {}\n'
                '{} --ffe\n'.format(PAPI_WEB_VERSION, PAPI_WEB_COPYRIGHT, PAPI_WEB_URL, EXE_FILENAME))


def create_zip():
    logger.info('Creating archive {}...'.format(ZIP_FILE))
    with ZipFile(ZIP_FILE, 'w') as zip_file:
        os.chdir(PROJECT_DIR.resolve())
        for folder_name, sub_folders, file_names in os.walk('.'):
            zip_file.write(folder_name, folder_name)
        for folder_name, sub_folders, file_names in os.walk('.'):
            for filename in file_names:
                file_path: Path = Path(folder_name, filename)
                zip_file.write(file_path, file_path)


def build_test():
    os.chdir(Path(__file__).resolve().parents[0])
    if not TEST_DIR.is_dir():
        logger.info('Creating test environment in {}...'.format(TEST_DIR))
        TEST_DIR.mkdir(parents=True)
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
