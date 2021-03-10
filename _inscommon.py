import subprocess
import os.path
import logging
from configparser import ConfigParser, ExtendedInterpolation


class InstallationException(Exception):
    """
    Special type of exception, designed to distinguish internal errors from other, more environment specific
    """
    def __init__(self, component: str, message: str):
        """
        Initializes the exception with component name and detailed message
        :param component: the name of particular component / activity of the installer
        :param message: the details about error
        """
        Exception.__init__(self, f'[{component.upper()}] {message}')


class InstallationComponent:
    """
    Base class for all installation activities
    Provides access to the name of component and to logging facility
    """
    def __init__(self):
        pass

    def _component_name(self):
        raise NotImplementedError()

    def log(self) -> logging.Logger:
        return logging.getLogger(self._component_name())

    def raise_exception(self, message: str):
        raise InstallationException(component=self._component_name(), message=message)


class SubprocessAction(InstallationComponent):

    def __init__(self):
        InstallationComponent.__init__(self)
        self.error = None

    def _component_name(self):
        return 'COMMAND'

    def execute(self, command: list, must_succeed: bool = False):

        exec_res = subprocess.run(command, capture_output=True)

        if exec_res and exec_res.returncode == 0:
            # success, catch output
            self.log().debug(f'Executing {str(command)} SUCCEEDED. '
                             f'Stdout: <{exec_res.stdout.decode("utf-8").rstrip()}>')
        else:
            self.error = f'Executing {str(command)} FAILED.\n' \
                         f'Return code: {exec_res.returncode if exec_res else "N/A"};\n' \
                         f'Stdout: <{exec_res.stdout.decode("utf-8").rstrip() if exec_res and exec_res.stdout else "N/A"}>;\n' \
                         f'Stderr: <{exec_res.stderr.decode("utf-8").rstrip() if exec_res and exec_res.stderr else "N/A"}>'

            if must_succeed:
                self.raise_exception(self.error)
            else:
                self.log().warning(self.error)


class ServiceControl(SubprocessAction):

    def __init__(self, service_name: str):
        SubprocessAction.__init__(self)
        self.service_name = service_name

    def _component_name(self):
        return 'SYSTEMCTL'

    def stop(self):
        self.execute(command=['sudo', 'systemctl', 'stop', self.service_name], must_succeed=False)

    def disable(self):
        self.execute(command=['sudo', 'systemctl', 'disable', self.service_name], must_succeed=False)

    def install(self):
        self.execute(command=['sudo', 'systemctl', 'daemon-reload'], must_succeed=True)
        self.execute(command=['sudo', 'systemctl', 'enable', self.service_name+".service"], must_succeed=True)

    def start(self):
        self.execute(command=['sudo', 'systemctl', 'start', self.service_name], must_succeed=True)


class VenvManager(SubprocessAction):

    def __init__(self, venv_path: str):
        SubprocessAction.__init__(self)
        self._path = venv_path

    def _component_name(self):
        return 'VENV'

    def create(self):
        self.execute(command=['sudo', 'python3', '-m', 'venv', '--clear', self._path], must_succeed=True)

    def remove(self):
        self.execute(command=['sudo', 'rm', '-rd', self._path], must_succeed=False)

    def install_module(self, _module: str):
        self.execute(command=['sudo', os.path.join(self._path, 'bin', 'pip3'), 'install', _module], must_succeed=True)


class LocalModuleManager(SubprocessAction):

    def __init__(self, lookup_paths: list, venv_path: str):
        SubprocessAction.__init__(self)
        self._lookup_paths = lookup_paths
        self.modules_target_path = os.path.join(venv_path, 'lib', 'python3.7', 'site-packages')
        self._venv_path = venv_path
        self.base_dir = os.path.dirname(self._venv_path)
        self.main_module_target_path = None  # will be intialized during installation

    def _component_name(self):
        return 'MODULE'

    def _module_file(self, _module: str):
        return _module if _module.endswith('.py') or _module.endswith('.wsgi') else _module + '.py'

    def _find_module(self, _module):
        module_path = list()
        module_file = self._module_file(_module)
        for path in self._lookup_paths:
            p = os.path.join(path, module_file)
            if os.path.exists(p) and os.path.isfile(p):
                module_path.append(p)

        if len(module_path) > 1:
            self.raise_exception(
                message=f'The module {_module} has been located in multiple locations: {str(module_path)}. '
                        f'The installation cannot continue')

        if len(module_path) == 0:
            self.raise_exception(message=f'The module {_module} was not located in none of: {str(self._lookup_paths)}')

        return module_path[0]

    def install_module(self, _module: str):
        module_path = self._find_module(_module=_module)

        # copy the located .py file to target directory
        target_path = os.path.join(self.modules_target_path, self._module_file(_module=_module))
        self.execute(['sudo', 'mkdir', '-p', os.path.dirname(target_path)], must_succeed=True)
        self.execute(['sudo', 'cp', '-u', '-r', module_path, target_path], must_succeed=True)

    def install_main_module(self, _main_module: str) -> str:
        main_module_file = self._find_module(_main_module)

        # ensure target dir exists
        self.main_module_target_path = os.path.join(self.base_dir,
                                                    os.path.basename(self._module_file(_module=_main_module)))

        with open(main_module_file, 'r') as _origin, open(self.main_module_target_path, 'w', encoding='utf-8') as _target:
            shebang = _origin.readline()
            if not shebang.startswith('#!'):
                self.raise_exception(f'First code line in main module {_main_module} does not seem to contain shebang')

            shebang = '#!'+os.path.join(self._venv_path, 'bin', 'python3')+'\n'
            _target.write(shebang)
            _target.writelines(_origin.readlines())

        # ensure it is executable!
        self.execute(['chmod', '-v', 'u+x', self.main_module_target_path])

        return self.main_module_target_path

    def install_file(self, _module_file: str) -> str:
        file_path = self._find_module(_module_file)

        target_path = os.path.join(self.base_dir, os.path.basename(file_path))

        self.execute(['sudo', 'mkdir', '-p', os.path.dirname(target_path)], must_succeed=True)
        self.execute(['sudo', 'cp', '-u', '-r', file_path, target_path], must_succeed=True)

        return target_path

    def remove_all(self):
        self.execute(command=['sudo', 'rm', '-rd', self.base_dir], must_succeed=False)


class SystemdServiceCreator(SubprocessAction, ConfigParser):
    SECTION_UNIT = 'Unit'
    SECTION_SERVICE = 'Service'

    OPTION_DESCRIPTION = 'Description'
    OPTION_EXEC_START = 'ExecStart'
    OPTION_WORKING_DIRECTORY = 'WorkingDirectory'

    def __init__(self, template_file: str,  target_file: str):
        InstallationComponent.__init__(self)
        ConfigParser.__init__(self)
        self.optionxform = str  # preserves case-sensitivity of options
        self.target_file = target_file
        self.read(template_file)

    def _component_name(self):
        return 'SYSTEMD-INI'

    def create(self, exec_start: str, working_directory: str, service_descripton: str = None) -> str:
        if service_descripton:
            self.set(self.SECTION_UNIT, self.OPTION_DESCRIPTION, service_descripton)
        if exec_start:
            self.set(self.SECTION_SERVICE, self.OPTION_EXEC_START, exec_start)
        if working_directory:
            self.set(self.SECTION_SERVICE, self.OPTION_WORKING_DIRECTORY, working_directory)

        with open(self.target_file, 'w', encoding='utf-8') as _w_file:
            self.write(_w_file, space_around_delimiters=False)

        return self.target_file

    def remove(self):
        self.execute(command=['sudo', 'rm', '-fv', self.target_file], must_succeed=False)
