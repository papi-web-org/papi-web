import os
import shutil
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from logging import Logger
from PyInstaller.__main__ import run
from common.papi_web_config import PAPI_WEB_VERSION, PAPI_WEB_COPYRIGHT, PAPI_WEB_URL
from common.logger import get_logger

logger: Logger = get_logger()

BUILD_DIR: Path = Path('build')
DIST_DIR: Path = Path('dist')
DATA_DIR: Path = Path('export-data')
CUSTOM_DIR: Path = Path('custom')
basename: str = f'papi-web-{PAPI_WEB_VERSION}'
EXPORT_DIR: Path = Path('..') / 'export'
PROJECT_DIR: Path = EXPORT_DIR / basename
ZIP_FILE: Path = EXPORT_DIR / f'{basename}.zip'
EXE_FILENAME: str = basename + '.exe'
SPEC_FILE: Path = Path('.') / f'{basename}.spec'
TEST_DIR: Path = Path('..') / 'test'


def clean(clean_zip: bool):
    os.chdir(Path(__file__).resolve().parents[0])
    for d in [BUILD_DIR, DIST_DIR, PROJECT_DIR, ]:
        if Path(d).is_dir():
            logger.info(f'Deleting folder {d}...')
            shutil.rmtree(d)
    if SPEC_FILE.is_file():
        logger.info(f'Deleting file {SPEC_FILE}...')
        SPEC_FILE.unlink()
    if clean_zip:
        if ZIP_FILE.is_file():
            logger.info(f'Deleting file {ZIP_FILE}...')
            ZIP_FILE.unlink()


def build_exe():
    os.chdir(Path(__file__).resolve().parents[0])
    pyinstaller_params = [
        '--clean',
        '--noconfirm',
        '--name=' + basename,
        '--onefile',
        '--hiddenimport=chessevent',
        '--hiddenimport=common',
        '--hiddenimport=data',
        '--hiddenimport=database',
        '--hiddenimport=ffe',
        '--hiddenimport=test',
        '--hiddenimport=web',
        '--paths=.',
        'papi_web.py',
    ]
    run(pyinstaller_params)


def create_project():
    os.chdir(Path(__file__).resolve().parents[0])
    logger.info(f'Creating folder {PROJECT_DIR} from {DATA_DIR}...')
    shutil.copytree(DATA_DIR, PROJECT_DIR)
    dist_exe_file: Path = DIST_DIR / EXE_FILENAME
    logger.info(f'Moving {dist_exe_file} to {PROJECT_DIR}...')
    shutil.move(str(dist_exe_file), str(PROJECT_DIR / 'bin'))
    target_dir: Path = PROJECT_DIR / CUSTOM_DIR
    logger.info(f'Copying {CUSTOM_DIR} to {target_dir}...')
    shutil.copytree(CUSTOM_DIR, target_dir)
    target_file: Path = PROJECT_DIR / 'server.bat'
    logger.info(f'Creating batch file {target_file}...')
    with open(target_file, 'wt') as f:
        f.write(f'@echo off\n'
                f'echo Démarrage du serveur Papi-web, veuillez patienter...\n'
                f'@rem Papi-web {PAPI_WEB_VERSION} - {PAPI_WEB_COPYRIGHT} - {PAPI_WEB_URL}\n'
                f'bin\\{EXE_FILENAME} --server\n'
                f'pause\n')
    target_file = PROJECT_DIR / 'ffe.bat'
    logger.info(f'Creating batch file {target_file}...')
    with open(target_file, 'wt') as f:
        f.write(f'@echo off\n'
                f'echo Connexion de Papi-web au serveur fédéral, veuillez patienter...\n'
                f'@rem Papi-web {PAPI_WEB_VERSION} - {PAPI_WEB_COPYRIGHT} - {PAPI_WEB_URL}\n'
                f'bin\\{EXE_FILENAME} --ffe\n'
                f'pause\n')
    target_file = PROJECT_DIR / 'chessevent.bat'
    logger.info(f'Creating batch file {target_file}...')
    with open(target_file, 'wt') as f:
        f.write(f'@echo off\n'
                f'echo Connexion de Papi-web à Chess Event, veuillez patienter...\n'
                f'@rem Papi-web {PAPI_WEB_VERSION} - {PAPI_WEB_COPYRIGHT} - {PAPI_WEB_URL}\n'
                f'bin\\{EXE_FILENAME} --chessevent\n'
                f'pause\n')


def create_zip():
    logger.info(f'Creating archive {ZIP_FILE}...')
    with ZipFile(ZIP_FILE, 'w', ZIP_DEFLATED) as zip_file:
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
        logger.info(f'Creating test environment in {TEST_DIR}...')
        TEST_DIR.mkdir(parents=True)
    else:
        logger.info(f'Updating test environment in {TEST_DIR}...')
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
