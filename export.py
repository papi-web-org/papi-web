import os
import shutil
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from logging import Logger
from PyInstaller.__main__ import run
from common.papi_web_config import PapiWebConfig
from common.logger import get_logger

logger: Logger = get_logger()

BUILD_DIR: Path = Path('build')
DIST_DIR: Path = Path('dist')
DATA_DIR: Path = Path('export-data')
basename: str = f'papi-web-{PapiWebConfig().version}'
EXPORT_DIR: Path = Path('..') / 'export'
PROJECT_DIR: Path = EXPORT_DIR / basename
ZIP_FILE: Path = EXPORT_DIR / f'{basename}.zip'
EXE_FILENAME: str = basename + '.exe'
SPEC_FILE: Path = Path('.') / f'{basename}.spec'
TEST_DIR: Path = Path('..') / 'test'
ICON_FILE: Path = Path('.') / 'web' / 'static' / 'images' / 'papi-web.ico'


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
        '--icon=web/static/images/papi-web.ico',
        'papi_web.py',
    ]
    files: list[Path] = []
    web_dir = Path('.') / 'web'
    files += [file for file in Path('web/templates').glob('**/*') if file.is_file()]
    static_dir = web_dir / 'static'
    files += [file for file in Path('web/static/images').glob('**/*') if file.is_file()]
    files += [file for file in Path('web/static/css').glob('**/*') if file.is_file()]
    files += [file for file in Path('web/static/js').glob('**/*') if file.is_file()]
    lib_dir = static_dir / 'lib'
    bootstrap_dir = lib_dir / 'bootstrap' / f'bootstrap-{PapiWebConfig().bootstrap_version}-dist'
    files += [
        bootstrap_dir / 'css' / 'bootstrap.min.css',
        bootstrap_dir / 'css' / 'bootstrap.min.css.map',
        bootstrap_dir / 'js' / 'bootstrap.bundle.min.js',
        bootstrap_dir / 'js' / 'bootstrap.bundle.min.js.map',
    ]
    bootstrap_icons_dir = lib_dir / 'bootstrap-icons' / f'bootstrap-icons-{PapiWebConfig().bootstrap_icons_version}'
    files += [
        bootstrap_icons_dir / 'font' / 'bootstrap-icons.min.css',
    ]
    files += [
        file for file in (bootstrap_icons_dir / 'font' / 'fonts').glob('**/*')
        if file.is_file()
    ]
    jquery_file = lib_dir / 'jquery' / f'jquery-{PapiWebConfig().jquery_version}.min.js'
    files += [jquery_file, ]
    htmx_dir = lib_dir / 'htmx' / f'htmx-{PapiWebConfig().htmx_version}'
    files += [
        file for file in htmx_dir.glob('**/*')
        if file.is_file()
    ]
    sortable_dir = lib_dir / 'sortable' / f'sortable-{PapiWebConfig().sortable_version}'
    files += [
        file for file in sortable_dir.glob('**/*')
        if file.is_file()
    ]
    htmx_sortable_file = lib_dir / 'htmx' / f'htmx-sortable.js'
    files += [htmx_sortable_file, ]
    jstree_dir = lib_dir / 'jstree' / f'jstree-{PapiWebConfig().jstree_version}-dist'
    files += [
        file for file in jstree_dir.glob('**/*')
        if file.is_file()
    ]
    sql_dir: Path = Path('.') / 'database' / 'sql'
    files += [sql_dir / 'create_event.sql', ]
    yml_dir: Path = Path('.') / 'database' / 'yml'
    files += list(yml_dir.glob('*.yml'))
    for file in files:
        pyinstaller_params.append(f'--add-data={file};{file.parent}')
    files: list[Path] = []
    files += [
        file for file in Path('venv/Lib/site-packages/litestar/middleware/exceptions/templates').glob('**/*')
        if file.is_file()
    ]
    for file in files:
        pyinstaller_params.append(f'--add-data={file};litestar/middleware/exceptions/templates')
    run(pyinstaller_params)


def create_project():
    os.chdir(Path(__file__).resolve().parents[0])
    logger.info(f'Creating folder {PROJECT_DIR} from {DATA_DIR}...')
    shutil.copytree(DATA_DIR, PROJECT_DIR)
    dist_exe_file: Path = DIST_DIR / EXE_FILENAME
    logger.info(f'Moving {dist_exe_file} to {PROJECT_DIR}...')
    bin_dir: Path = PROJECT_DIR / 'bin'
    bin_dir.mkdir(exist_ok=True)
    shutil.move(dist_exe_file, bin_dir)
    custom_path: Path = PapiWebConfig().custom_path
    target_dir: Path = PROJECT_DIR / custom_path.name
    logger.info(f'Copying {custom_path} to {target_dir}...')
    shutil.copytree(custom_path, target_dir)
    target_file: Path = PROJECT_DIR / 'server.bat'
    logger.info(f'Creating batch file {target_file}...')
    with open(target_file, 'wt') as f:
        f.write(f'@echo off\n'
                f'echo Démarrage du serveur Papi-web, veuillez patienter...\n'
                f'@rem Papi-web {PapiWebConfig().version} - {PapiWebConfig().copyright} - {PapiWebConfig().url}\n'
                f'bin\\{EXE_FILENAME} --server\n'
                f'pause\n')
    target_file = PROJECT_DIR / 'ffe.bat'
    logger.info(f'Creating batch file {target_file}...')
    with open(target_file, 'wt') as f:
        f.write(f'@echo off\n'
                f'echo Connexion de Papi-web au serveur fédéral, veuillez patienter...\n'
                f'@rem Papi-web {PapiWebConfig().version} - {PapiWebConfig().copyright} - {PapiWebConfig().url}\n'
                f'bin\\{EXE_FILENAME} --ffe\n'
                f'pause\n')
    target_file = PROJECT_DIR / 'chessevent.bat'
    logger.info(f'Creating batch file {target_file}...')
    with open(target_file, 'wt') as f:
        f.write(f'@echo off\n'
                f'echo Connexion de Papi-web à Chess Event, veuillez patienter...\n'
                f'@rem Papi-web {PapiWebConfig().version} - {PapiWebConfig().copyright} - {PapiWebConfig().url}\n'
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
