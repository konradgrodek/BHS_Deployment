#!/usr/bin/python3

# INstall SERVice script

from _inscommon import *

import sys
import os.path
import logging


class CommandlineConfig:
    """
    Keeps the configuration of the installer passed in commandline arguments
    """

    DBTEST = '--db:test'
    UNINSTALL = ['--uninstall', '-u']
    START = '--start'

    USAGE = 'Usage:\n' \
            'sudo ./inserv.py ./install/configuration_file.ini [optional parameters]\n' \
            'Optional parameters are:\n' \
            f'[{DBTEST}] if present, the service should be installed to write to test database, not production\n' \
            f'[{UNINSTALL}] if present, the installer will uninstall given service\n' \
            f'[{START}] if present, the installer will start the service immediately after installation'

    COMPONENT = 'commandline config'

    def __init__(self):
        """
        Initializes the configuration from sys.argv
        """
        self.dbtest_mode = False
        self.install = True
        self.start_immediately = False

        if len(sys.argv) < 2:
            # interactive mode
            self.config_file = input('Enter configuration file, or just try the service short name > ')
            self.dbtest_mode = input('Test database? (Y/N) > ') == 'Y'
        else:
            self.config_file = sys.argv[1]

        for arg in sys.argv[2:]:
            if arg == CommandlineConfig.DBTEST:
                self.dbtest_mode = True
            elif arg in CommandlineConfig.UNINSTALL:
                self.install = False
            elif arg == CommandlineConfig.START:
                self.start_immediately = True
            else:
                raise InstallationException(CommandlineConfig.COMPONENT,
                                            f'Parameter not recognized: {arg}. {CommandlineConfig.USAGE}')

        if not os.path.exists(self.config_file):
            # try to guess config
            self.config_file = f'./install/{self.config_file}.install.ini'

            if not os.path.exists(self.config_file):
                raise InstallationException(CommandlineConfig.COMPONENT,
                                            f'Path to the file with installation configuration: {self.config_file} '
                                            f'points to an invalid location')

        if not os.path.isfile(self.config_file):
            raise InstallationException(CommandlineConfig.COMPONENT,
                                        f'Path to the file with installation configuration: {self.config_file} '
                                        f"does not point to an actual file")

        if not self.install and self.start_immediately:
            raise InstallationException(CommandlineConfig.COMPONENT,
                                        f'Instructed both to uninstall and to start the service. '
                                        f'Make up your mind, the two options are contradicting')

        try:
            with open(self.config_file, 'r'):
                pass
        except PermissionError as pererr:
            raise InstallationException(CommandlineConfig.COMPONENT,
                                        f'The file with installation configuration: {self.config_file} '
                                        f"cannot be opened using current security context. "
                                        f"Try with sudo. ({str(pererr)})")

        self.install_config_file_name = os.path.split(os.path.splitext(self.config_file)[0])[-1]


class ServiceConfig(Config):
    COMMON_CFG_FILE = "common.install.ini"

    SECTION_COMMON_EXTERNAL_MODULES = "COMMON-EXTERNALS"
    SECTION_COMMON_MODULES = "COMMON-MODULES"

    REQUIRED_OPTIONS = [
                (Config.SECTION_SERVICE, Config.OPTION_NAME),
                (Config.SECTION_GENERAL, Config.OPTION_SHORT_NAME),
                (Config.SECTION_PATH, Config.OPTION_VENV),
                (Config.SECTION_PATH, Config.OPTION_SERVICE_INI),
                (Config.SECTION_MODULES, Config.OPTION_MAIN_MODULE),
                (Config.SECTION_DATABASE, Config.OPTION_HOST)]

    def __init__(self, config_file):
        Config.__init__(self, config_file)

        config_dir = os.path.dirname(config_file)
        common_cfg = os.path.join(config_dir, ServiceConfig.COMMON_CFG_FILE)

        if not os.path.exists(common_cfg):
            self.raise_exception(
                f'The file with common installation configuration: {common_cfg} '
                f"does not exist")

        self.read(common_cfg)
        self._verfy_config(ServiceConfig.REQUIRED_OPTIONS)

    def get_external_modules(self) -> list:
        _all_modules = list()
        if self.has_section(section=self.SECTION_COMMON_EXTERNAL_MODULES):
            _all_modules = self.options(section=self.SECTION_COMMON_EXTERNAL_MODULES)

        if self.has_section(section=self.SECTION_EXTERNAL_MODULES):
            _all_modules.extend(self.options(section=self.SECTION_EXTERNAL_MODULES))

        return _all_modules

    def get_modules(self) -> list:
        _modules = list()
        if self.has_section(section=self.SECTION_COMMON_MODULES):
            _modules = self.options(section=self.SECTION_COMMON_MODULES)

        if self.has_section(section=self.SECTION_MODULES):
            internal = self.options(section=self.SECTION_MODULES)
            for intern in internal:
                if intern != self.OPTION_MAIN_MODULE:
                    _modules.append(intern)

        return _modules

    def get_path_systemd_template(self) -> str:
        return './$template.service'


def init_logging(cmdline: CommandlineConfig) -> logging.Logger:
    logging.basicConfig(
        filename=os.path.join('../BHS_Services/deployment/x_log',
                           f'{datetime.today().strftime("%Y%m%d%H%M%S")}_{cmdline.install_config_file_name}.log'),
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
    try:
        cmdline = CommandlineConfig()
        log = init_logging(cmdline)
        config = ServiceConfig(config_file=cmdline.config_file)
        service_ctrl = ServiceControl(service_name=config.get_service_full_name())
        venv_mngr = VenvManager(venv_path=config.get_path_venv())
        module_mngr = LocalModuleManager(lookup_paths=config.get_modules_lookup_paths(),
                                         venv_path=config.get_path_venv())
        systemd_creator = SystemdServiceCreator(template_file=config.get_path_systemd_template(),
                                                target_file=config.get_path_systemd())
        ini_mngr = IniManager(target_dir=config.get_path_service_ini(),
                              ini_file=config.get_path_origin_service_ini())
        envini_creator = EnvIniCreator(target_file=config.get_path_service_env_ini())

        if cmdline.install:
            # install

            log.info(f'Installation initialized for service {config.get_service_full_name()}')

            service_ctrl.stop()
            log.info(f'Service {config.get_service_full_name()} stopped')

            service_ctrl.disable()
            log.info(f'Service {config.get_service_full_name()} disabled')

            venv_mngr.create()
            log.info(f'Virtual environment created @ {config.get_path_venv()}')

            externals = config.get_external_modules()
            for external in externals:
                venv_mngr.install_module(external)
                log.info(f'Module {external} installed')
            log.info(f'All external modules installed')

            modules = config.get_modules()
            for module in modules:
                module_mngr.install_module(module)
                log.info(f'Module {module} installed')
            log.info(f'All modules installed')

            main_module = config.get_main_module()
            module_mngr.install_main_module(_main_module=main_module)
            log.info(f'Main module {main_module} installed')

            service_log_dir = config.get_path_service_log()
            if not os.path.exists(service_log_dir):
                SubprocessAction().execute(['mkdir', '-p', service_log_dir])
                log.info(f'Service log dir {service_log_dir} created')

            SubprocessAction().execute(['chmod', 'ugo+rw', service_log_dir])
            log.info(f'Access rights to service log dir {service_log_dir} amended')

            ini_mngr.copy_ini()
            log.info(f'Service configuration file is copied to {ini_mngr.ini_target_file_path}')

            envini_creator.create(host=config.get_database_host(),
                                  db=config.get_database_db(cmdline.dbtest_mode),
                                  credentials=config.get_database_credentials())
            log.info(f'File with environment-specific settings created: {config.get_path_service_env_ini()}')

            systemd_config_path = systemd_creator.create(
                exec_start=module_mngr.main_module_target_path,
                service_descripton=config.get_service_description(),
                working_directory=os.path.dirname(module_mngr.main_module_target_path))
            log.info(f'Systemd configuration file created @ {systemd_config_path}')

            service_ctrl.install()
            log.info(f'Systemd instructed to enable new service')

            log.info(f'{config.get_service_full_name()} installed successfully')

            if cmdline.start_immediately:
                service_ctrl.start()
                log.info(f'{config.get_service_full_name()} started')

        else:
            # uninstall

            log.info(f'De-installation initialized for service {config.get_service_full_name()}')

            service_ctrl.stop()
            log.info(f'Service {config.get_service_full_name()} stopped')

            service_ctrl.disable()
            log.info(f'Service {config.get_service_full_name()} disabled')

            module_mngr.remove_all()
            log.info(f'The directory {module_mngr.base_dir} removed with all the content')

            systemd_creator.remove()
            log.info(f'The SYSTEMD file {systemd_creator.target_file} removed')

            #TODO systemctl reload?

            ini_mngr.remove()
            log.info(f'The directory {ini_mngr.ini_base_dir} removed')

            log.info(f'{config.get_service_full_name()} uninstalled')

    except InstallationException as e:
        sys.stderr.write(str(e))
