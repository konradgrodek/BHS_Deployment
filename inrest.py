from _inscommon import *
from configparser import ConfigParser, ExtendedInterpolation
from datetime import datetime
import sys


class Config(InstallationComponent, ConfigParser):
    """
    Keeps parsed content of installation config
    Subclasses built-in configparser.ConfigParser, so all handy methods are already here
    """
    COMPONENT = 'CONFIG'

    CREDENTIALS_FILE = ".credentials"

    SECTION_PATH = 'PATH'
    SECTION_EXTERNAL_MODULES = "EXTERNALS"
    SECTION_MODULES = 'MODULES'
    SECTION_REST = 'REST'

    OPTION_BASEPATH = "bin-base"
    OPTION_VENVPATH = "service-venv"
    OPTION_MAIN_MODULE = "main"
    OPTION_WSGI = "wsgi"
    OPTION_LOOKUP_PATH = 'module-path'
    OPTION_PORT = 'port'

    REQUIRED_OPTIONS = [(SECTION_PATH, OPTION_VENVPATH)]

    def __init__(self, config_file):
        InstallationComponent.__init__(self)
        ConfigParser.__init__(self, interpolation=ExtendedInterpolation(), allow_no_value=True)

        config_dir = os.path.dirname(config_file)
        credentials_file = os.path.join(config_dir, Config.CREDENTIALS_FILE)

        if not os.path.exists(credentials_file):
            self.raise_exception(
                f'The file with credentials: {credentials_file} '
                f"does not exist")

        self.read([credentials_file, config_file])
        self._verfy_config()

    def _component_name(self):
        return self.COMPONENT

    def _verfy_config(self):
        """
        Checks if all required configuration is in place
        """
        violations = list()
        for ropt in self.REQUIRED_OPTIONS:
            val = self.get(section=ropt[0], option=ropt[1])
            if not val:
                violations.append(f'missing option {ropt}')

        if len(violations) > 0:
            self.raise_exception(f'The configuration misses the following required options: {str(violations)}')

    def get_service_full_name(self) -> str:
        return 'BHS-Info-REST'

    def get_base_path(self) -> str:
        return self.get(section=self.SECTION_PATH, option=self.OPTION_VENVPATH)

    def get_path_venv(self) -> str:
        return self.get(section=self.SECTION_PATH, option=self.OPTION_VENVPATH)

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

    def get_modules_lookup_paths(self) -> list:
        _paths = list()
        if self.has_option(section=self.SECTION_PATH, option=self.OPTION_LOOKUP_PATH):
            split = self.get(section=self.SECTION_PATH, option=self.OPTION_LOOKUP_PATH).split(",")
            for el in split:
                _paths.append(el.strip())
        else:
            _paths.append("../")
        return _paths

    def get_path_systemd_template(self) -> str:
        return './$template.mod-wsgi.service'

    def get_path_systemd(self) -> str:
        return os.path.join('/etc/systemd/system', self.get_service_full_name()+'.service')

    def get_port(self) -> int:
        return self.getint(section=self.SECTION_REST, option=self.OPTION_PORT)


class ApacheModWsgiExpressServiceCreator(InstallationComponent):
    MOD_WSGI_EXPRESS = 'mod_wsgi-express'

    def __init__(self, template_file: str,  target_file: str):
        InstallationComponent.__init__(self)
        self.basic_creator = SystemdServiceCreator(template_file=template_file, target_file=target_file)

    def _component_name(self):
        return self.basic_creator._component_name()

    def _prepare_exec_start(self, mod_wsgi_location: str, wsgi_file: str, port: int):
        return f'{os.path.join(mod_wsgi_location,self.MOD_WSGI_EXPRESS)} start-server {wsgi_file} --port {port}'

    def create(self, mod_wsgi_location: str, wsgi_file_path: str, port: int) -> str:
        return self.basic_creator.create(
            exec_start=self._prepare_exec_start(
                mod_wsgi_location=mod_wsgi_location,
                wsgi_file=os.path.basename(wsgi_file_path),
                port=port),
            working_directory=os.path.dirname(wsgi_file_path))


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
    config = Config('install/rest-info.config.ini')
    service_ctrl = ServiceControl(service_name=config.get_service_full_name())
    venv_mngr = VenvManager(venv_path=config.get_path_venv())
    module_mngr = LocalModuleManager(lookup_paths=config.get_modules_lookup_paths(),
                                     venv_path=config.get_path_venv())
    systemd_creator = ApacheModWsgiExpressServiceCreator(template_file=config.get_path_systemd_template(),
                                                         target_file=config.get_path_systemd())

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

    # use mod_wsgi-express to run the server on systemd
    systemd_config_path = systemd_creator.create(mod_wsgi_location=config.get_path_mod_wsgi_express_location(),
                                                 wsgi_file_path=wsgi_file_path, port=config.get_port())
    log.info(f'Systemd configuration file created @ {systemd_config_path}')

    service_ctrl.install()
    log.info(f'Systemd instructed to enable new service')
