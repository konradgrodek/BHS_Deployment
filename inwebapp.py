#!/usr/bin/python3

# INstall WEB APPlication script

from _inscommon import *

import sys
from datetime import datetime


class WebAppConfig(Config):

    SECTION_FILES = 'FILES'

    OPTION_DJANGO_MANAGER = 'django-manager'
    OPTION_WSGI = "wsgi"

    REQUIRED_OPTIONS = [(Config.SECTION_PATH, Config.OPTION_VENV)]

    def __init__(self, config_file):
        Config.__init__(self, config_file)
        self._verfy_config(WebAppConfig.REQUIRED_OPTIONS)

    def get_service_full_name(self) -> str:
        return 'BHS-Info-WebApp'

    def get_service_description(self):
        return 'BHS Web Application Information Service'

    def get_path_mod_wsgi_express_location(self) -> str:
        return os.path.join(self.get_path_venv(), 'bin')

    def get_wsgi_file(self) -> str:
        return self.get(section=self.SECTION_MODULES, option=self.OPTION_WSGI)

    def get_external_modules(self) -> list:
        _modules = list()

        if self.has_section(section=self.SECTION_EXTERNAL_MODULES):
            _modules.extend(self.options(section=self.SECTION_EXTERNAL_MODULES))

        return _modules

    def get_modules(self) -> list:
        _modules = list()
        if self.has_section(section=self.SECTION_MODULES):
            internal = self.options(section=self.SECTION_MODULES)
            for intern in internal:
                if intern not in (self.OPTION_MAIN_MODULE, self.OPTION_WSGI):
                    _modules.append(intern)

        return _modules

    def get_files(self) -> list:
        return self.options(section=self.SECTION_FILES)

    def get_path_systemd_template(self) -> str:
        return './$template.mod-wsgi.apachectl.service'

    def get_path_origin_django_manager(self) -> str:
        if self.has_option(self.SECTION_PATH, self.OPTION_DJANGO_MANAGER):
            return self.get(self.SECTION_PATH, self.OPTION_DJANGO_MANAGER)

        _pths = self.get_modules_lookup_paths()
        for _pth in _pths:
            _tryit = os.path.join(_pth, 'manage.py')
            if os.path.exists(_tryit) and os.path.isfile(_tryit):
                self.set(self.SECTION_PATH, self.OPTION_DJANGO_MANAGER, _tryit)

        if not self.has_option(self.SECTION_PATH, self.OPTION_DJANGO_MANAGER):
            self.raise_exception(f'Cannot locate Django manager in none of paths {str(_pths)}')

        return self.get(self.SECTION_PATH, self.OPTION_DJANGO_MANAGER)

    def get_path_target_django_manager(self) -> str:
        return os.path.join(self.get_path_base_dir(), 'manage.py')

    def get_path_target_dir_statics(self) -> str:
        return os.path.join(self.get_path_base_dir(), 'static')


class StaticFilesManager(SubprocessAction):

    def __init__(self, venv_python: str, django_mngr_path: str, target_path: str):
        InstallationComponent.__init__(self)
        self.target_path = target_path
        self.venv_python = venv_python
        self.origin_path = './static'
        self.django_manager = django_mngr_path
        self.collectstatic_command = 'collectstatic'

    def _component_name(self):
        return 'STATICFILES'

    def _collect(self):
        self.execute(command=['sudo',
                              self.venv_python,
                              self.django_manager,
                              self.collectstatic_command,
                              '--noinput'],
                     must_succeed=True)

        # not needed to double-check if the dir exists - the statics are now installed directly in the target dir
        # if not os.path.exists(self.origin_path):
        #    self.raise_exception(f'The command to collect static files succeeded, '
        #                         f'but dir {self.origin_path} has been located')

        self.log().debug(f'Static files collected in {self.origin_path}')

    def _copy_to_target(self):
        self.execute(command=['sudo', 'cp', '-frv', self.origin_path, self.target_path])

        self.log().debug(f'Collected static files copied from {self.origin_path} to {self.target_path}')

    def _remove_temp(self):
        self.execute(command=['sudo', 'rm', '-frdv', self.origin_path], must_succeed=True)

        self.log().debug(f'Temporary directory with static files {self.origin_path} has been removed')

    def install(self):
        self._collect()
        # originally, the static were collected in temporary folder, then moved to target 'manually'
        # this did not work, because collectstatic created link (in apache config) to the place
        # where it actually generated (collected) files. I found no easy way to work around that
        # now BHS_Info\settings.py contains hardcoded target path, so the manage.py collectstatic works correctly

        # self._copy_to_target()
        # self._remove_temp()


class ApacheModWsgiConfigurator(SubprocessAction):

    def __init__(self,
                 template_file: str,
                 target_file: str,
                 venv_python: str,
                 django_mngr_path: str,
                 apache_config_dir_path: str,
                 working_dir: str):
        SubprocessAction.__init__(self)
        self.basic_creator = SystemdServiceCreator(template_file=template_file, target_file=target_file)
        self.apache_config_dir_path = apache_config_dir_path
        self.django_mngr_path = django_mngr_path
        self.venv_python = venv_python
        self.working_dir = working_dir
        self.startup_script_path = '/etc/rc.local'

    def _component_name(self):
        return 'APACHE-CONF'

    def apachectl(self):
        return os.path.join(self.apache_config_dir_path, "apachectl")

    def configure(self):
        self.execute(command=['sudo',
                              self.venv_python,
                              self.django_mngr_path,
                              'runmodwsgi',
                              '--setup-only',
                              '--port=80',
                              '--user=www-data', '--group=www-data',
                              f'--pythonpath={self.venv_python}',
                              f'--working-directory={self.working_dir}',
                              f'--server-root={self.apache_config_dir_path}',
                              '--log-directory=/var/log/bhs/web-info',
                              '--process-name=BHS.WebInfo',
                              '--lang=pl_PL.UTF-8', '--locale=pl_PL.UTF-8']
                     , must_succeed=True)

    def setup_on_startup(self):
        """
        Ensures the script /etc/rc.local contains apache startup script execution
        """
        # first, verify if the script contains the line and it is not commented
        already_set_up = False
        startup_script_content = list()
        exit_0_index = None
        startup_command = f'sudo {self.apachectl()} start'

        self.log().debug(f'Adding {startup_command} to {self.startup_script_path}')

        with open(self.startup_script_path, 'r') as startup_script:
            startup_script_content = startup_script.readlines()
            i = 0
            for line in startup_script_content:
                if line.strip() == startup_command:
                    already_set_up = True
                if line.strip() == 'exit 0':
                    exit_0_index = i
                i += 1

        self.log().debug(f'Startup script {"already contains" if already_set_up else "does not contain"} the command.')
        if exit_0_index:
            self.log().debug(f'"exit 0" was located at index {exit_0_index}')
        else:
            self.log().warning(f'"exit 0" was not found in {self.startup_script_path}. This can cause problems!')

        if not already_set_up:
            insert_command_at = exit_0_index if exit_0_index is not None else len(startup_script_content)
            modified_startup_script_content = startup_script_content[:insert_command_at]
            modified_startup_script_content.extend([os.linesep, startup_command+os.linesep, os.linesep])
            modified_startup_script_content.extend(startup_script_content[insert_command_at:])

            with open(self.startup_script_path, 'w') as startup_script:
                for line in modified_startup_script_content:
                    startup_script.write(line)


class ApacheController(SubprocessAction):

    def __init__(self, apache_ctrl: str):
        SubprocessAction.__init__(self)
        self.apache_ctrl = apache_ctrl

    def stop(self) -> bool:
        """
        Stops the apache service if it is already installed
        :return: True if the service is already installed
        """
        if not os.path.exists(self.apache_ctrl):
            return False

        self.execute(command=['sudo', self.apache_ctrl, 'stop'], must_succeed=False)

        return True


def init_logging() -> logging.Logger:
    logging.basicConfig(
        filename=os.path.join('x_log', f'{datetime.today().strftime("%Y%m%d%H%M%S")}_wsgi.log'),
        level=logging.DEBUG,
        format='%(asctime)s %(name)s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logger = logging.getLogger()
    stream_hdlr = logging.StreamHandler(sys.stdout)
    stream_hdlr.setLevel(logging.INFO)
    stream_hdlr.setFormatter(logger.handlers[0].formatter)
    logger.addHandler(stream_hdlr)
    return logger


if __name__ == '__main__':
    cmdline = CommandlineConfig()
    log = init_logging()
    # 'install/webapp-info.config.ini'
    config = WebAppConfig(config_file=cmdline.config_file)
    venv_mngr = VenvManager(venv_path=config.get_path_venv())
    module_mngr = LocalModuleManager(lookup_paths=config.get_modules_lookup_paths(),
                                     venv_path=config.get_path_venv())
    statics_mngr = StaticFilesManager(venv_python=venv_mngr.get_python(),
                                      django_mngr_path=config.get_path_origin_django_manager(),
                                      target_path=config.get_path_base_dir())
    ini_mngr = IniManager(target_dir=config.get_path_service_ini(),
                          ini_file=config.get_path_origin_service_ini())
    apache_config_mgr = ApacheModWsgiConfigurator(template_file=config.get_path_systemd_template(),
                                                  target_file=config.get_path_systemd(),
                                                  venv_python=venv_mngr.get_python(),
                                                  django_mngr_path=config.get_path_target_django_manager(),
                                                  apache_config_dir_path=config.get_path_service_ini(),
                                                  working_dir=config.get_path_base_dir())
    apache_ctrl = ApacheController(apache_ctrl=apache_config_mgr.apachectl())

    if cmdline.install:

        log.info(f'Installation initialized for service {config.get_service_full_name()}'
                 f'{" [minimal update only mode]" if cmdline.update_only else ""}')

        apache_ctrl.stop()
        log.info(f'Apache stopped')

        if not cmdline.update_only:
            venv_mngr.create()
            log.info(f'Virtual environment created @ {config.get_path_venv()}')

            # installing external modules
            externals = config.get_external_modules()
            for external in externals:
                venv_mngr.install_module(external)
                log.info(f'Module {external} installed')
            log.info(f'All external modules installed')

        # installing BHS modules
        modules = config.get_modules()
        for module in modules:
            module_mngr.install_module(module)
            log.info(f'Module {module} installed')
        log.info(f'All modules installed')

        if not cmdline.update_only:
            # .wsgi file to instruct mod-wsgi how to create application
            wsgi_file = config.get_wsgi_file()
            wsgi_file_path = module_mngr.install_file(wsgi_file)
            log.info(f'WSGI file {wsgi_file} installed @ {wsgi_file_path}')

        # collect and install static files
        statics_mngr.install()
        log.info(f'Static files collected and installed in {statics_mngr.target_path}')

        # installing files
        files = config.get_files()
        for fle in files:
            module_mngr.install_file(_module_file=fle)
            log.info(f'File {fle} installed')
        log.info(f'All files installed')

        # configuration file
        ini_mngr.copy_ini()
        log.info(f'Service configuration file is copied to {ini_mngr.ini_target_file_path}')

        if not cmdline.update_only:
            # execute mod-wsgi-express configuration
            apache_config_mgr.configure()
            log.info(f"Django's runmodwsgi executed to create Apache configuration")

            # modify /etc/rc.local by adding apache startup command at the end
            apache_config_mgr.setup_on_startup()
            log.info(f'Apache added to startup script')

        log.info(f'Installation concluded!')

    else:
        # uninstall
        log.error('NOT IMPLEMENTED')
