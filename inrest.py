#!/usr/bin/python3

# INstall REST service script

from _inscommon import *

import sys
from datetime import datetime


class RestServiceConfig(Config):

    SECTION_REST = 'REST'

    OPTION_WSGI = "wsgi"
    OPTION_PORT = 'port'

    REQUIRED_OPTIONS = [(Config.SECTION_PATH, Config.OPTION_VENV)]

    def __init__(self, config_file):
        Config.__init__(self, config_file)
        self._verfy_config(RestServiceConfig.REQUIRED_OPTIONS)

    def get_service_full_name(self) -> str:
        return 'BHS-Info-REST'

    def get_service_description(self):
        return 'BHS REST Information Service'

    def get_path_mod_wsgi_express_location(self) -> str:
        return os.path.join(self.get_path_venv(), 'bin')

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

    def get_main_module(self) -> str:
        return self.get(section=self.SECTION_MODULES, option=self.OPTION_MAIN_MODULE)

    def get_wsgi_file(self) -> str:
        return self.get(section=self.SECTION_MODULES, option=self.OPTION_WSGI)

    def get_path_systemd_template(self) -> str:
        return './$template.mod-wsgi.service'

    def get_port(self) -> int:
        return self.getint(section=self.SECTION_REST, option=self.OPTION_PORT)


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
    log = init_logging()
    config = RestServiceConfig('install/rest-info.config.ini')
    service_ctrl = ServiceControl(service_name=config.get_service_full_name())
    venv_mngr = VenvManager(venv_path=config.get_path_venv())
    module_mngr = LocalModuleManager(lookup_paths=config.get_modules_lookup_paths(),
                                     venv_path=config.get_path_venv())
    systemd_creator = ApacheModWsgiExpressServiceCreator(template_file=config.get_path_systemd_template(),
                                                         target_file=config.get_path_systemd())

    ini_mngr = IniManager(target_dir=config.get_path_service_ini(),
                          ini_file=config.get_path_origin_service_ini())
    envini_creator = EnvIniCreator(target_file=config.get_path_service_env_ini())

    log.info(f'Installation initialized for BHS REST service')

    service_ctrl.stop()
    log.info(f'Service {config.get_service_full_name()} stopped')

    service_ctrl.disable()
    log.info(f'Service {config.get_service_full_name()} disabled')

    # create virtual environment
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

    # main module of the service
    main_module = config.get_main_module()
    main_module_path = module_mngr.install_file(main_module)
    log.info(f'Main module {main_module} installed @ {main_module_path}')

    # .wsgi file to instruct mod-wsgi how to create application
    wsgi_file = config.get_wsgi_file()
    wsgi_file_path = module_mngr.install_file(wsgi_file)
    log.info(f'WSGI file {wsgi_file} installed @ {wsgi_file_path}')

    ini_mngr.copy_ini()
    log.info(f'Service configuration file is copied to {ini_mngr.ini_target_file_path}')

    envini_creator.create(host=config.get_database_host(),
                          db=config.get_database_db(test_mode=False),
                          credentials=config.get_database_credentials())
    log.info(f'File with environment-specific settings created: {config.get_path_service_env_ini()}')

    # use mod_wsgi-express to run the server on systemd
    systemd_config_path = systemd_creator.create(mod_wsgi_location=config.get_path_mod_wsgi_express_location(),
                                                 wsgi_file_path=wsgi_file_path, port=config.get_port())
    log.info(f'Systemd configuration file created @ {systemd_config_path}')

    service_ctrl.install()
    log.info(f'Systemd instructed to enable new service')

    log.info(f'All done!')
