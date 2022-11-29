import enum
import logging
import os
import typing

import params
import results
import tkn.model

DEFAULT_IMAGE = 'eu.gcr.io/gardener-project/glci/job-image:0.1.0'

logger = logging.getLogger(__name__)

own_dir = os.path.abspath(os.path.dirname(__file__))
scripts_dir = os.path.join(own_dir)
steps_dir = os.path.join(own_dir, 'steps')


def extend_python_path_snippet(param_name: str):
    sd_name = os.path.basename(scripts_dir)
    return f'sys.path.insert(1,os.path.abspath(os.path.join("$(params.{param_name})","{sd_name}")))'


class ScriptType(enum.Enum):
    BOURNE_SHELL = 'sh'
    PYTHON3 = 'python3'


def task_step_script(
    script_type: ScriptType,
    callable: str,
    params: typing.List[tkn.model.NamedParam],
    results:  typing.List[tkn.model.NamedParam]=None,
    repo_path_param: typing.Optional[tkn.model.NamedParam]=None,
    path: str = None,
    inline_script: str = None,
):
    '''
    renders an inline-step-script, prepending a shebang, and appending an invocation
    of the specified callable (passing the given params). Either use path to inline
    script from a file or use inline inline_script to pass script directly

    '''

    if path and inline_script:
        raise ValueError("Either use path or inline_script but not both.")

    if path:
        with open(path) as f:
            script = f.read()
    elif inline_script:
        script = inline_script

    if script_type is ScriptType.PYTHON3:
        shebang = '#!/usr/bin/env python3'
        if repo_path_param:
            preamble = 'import sys,os;' + extend_python_path_snippet(repo_path_param.name)
        else:
            preamble = ''

        args = ','.join((
            f"{param.name.replace('-', '_')}='$(params.{param.name})'" for param in params
        ))
        if results:
            args += ',' + ','.join((
                f"{result.name.replace('-', '_')}='$(results.{result.name}.path)'"
                    for result in results
            ))
        callable_str = f'{callable}({args})'
    elif script_type is ScriptType.BOURNE_SHELL:
        shebang = '#!/usr/bin/env bash'
        preamble = ''
        args = ' '.join([f'"$(params.{param.name})"' for param in params])
        if results:
            args = ' ' + ' '.join([f'"$(results.{result.name}.path)"' for result in results])
        callable_str = f'{callable} {args}'

    if callable:
        return '\n'.join((
            shebang,
            preamble,
            script,
            callable_str,
        ))
    else:
        return '\n'.join((
            shebang,
            preamble,
            script,
        ))


def clone_step(
    params: params.AllParams,
    env_vars: typing.List[typing.Dict] = [],
    volume_mounts: typing.List[typing.Dict] = [],
):
    step_params = [
        params.committish,
        params.giturl,
        params.repo_dir,
        params.gardenlinux_committish,
        params.gardenlinux_giturl,
        params.gardenlinux_repo_dir,
    ]

    step = tkn.model.TaskStep(
        name='clone-repo-step',
        image=DEFAULT_IMAGE,
        script=task_step_script(
            path=os.path.join(steps_dir, 'clone_repo_step.py'),
            script_type=ScriptType.PYTHON3,
            callable='clone_and_copy',
            params=step_params,
            repo_path_param=params.repo_dir,
        ),
        volumeMounts=volume_mounts,
        env=env_vars,
    )

    return step, step_params


def status_step(
    params: params.AllParams,
    env_vars: typing.List[typing.Dict] = [],
    volume_mounts: typing.List[typing.Dict] = [],
):
    step_params = [
        params.committish,
        params.giturl,
        params.pipeline_run_name,
        params.namespace,
    ]

    step = tkn.model.TaskStep(
        name='update-status-step',
        image=DEFAULT_IMAGE,
        script=task_step_script(
            path=os.path.join(steps_dir, 'update_status.py'),
            script_type=ScriptType.PYTHON3,
            callable='update_status',
            params=step_params,
            repo_path_param=params.repo_dir,
        ),
        volumeMounts=volume_mounts,
        env=env_vars,
    )

    return step, step_params


def promote_single_step(
    params: params.AllParams,
    env_vars: typing.List[typing.Dict] = [],
    volume_mounts: typing.List[typing.Dict] = [],
):
    step_params = [
        params.architecture,
        params.cicd_cfg_name,
        params.gardenlinux_committish,
        params.gardenlinux_epoch,
        params.modifiers,
        params.platform,
        params.build_targets,
        params.version,
    ]
    env_vars.append({
        'name': 'GARDENLINUX_PATH',
        'value': params.gardenlinux_repo_dir.default,
    })
    step = tkn.model.TaskStep(
        name='promote-step',
        image='$(params.step_image)',
        script=task_step_script(
            path=os.path.join(steps_dir, 'promote_step.py'),
            script_type=ScriptType.PYTHON3,
            callable='promote_single_step',
            params=step_params,
            repo_path_param=params.repo_dir,
        ),
        volumeMounts=volume_mounts,
        env=env_vars,
    )
    return step, step_params


def promote_step(
    params: params.AllParams,
    results: results.AllResults,
    env_vars: typing.List[typing.Dict] = [],
    volume_mounts: typing.List[typing.Dict] = [],
):
    step_params = [
        params.cicd_cfg_name,
        params.gardenlinux_committish,
        params.flavour_set_name,
        params.gardenlinux_epoch,
        params.promote_target,
        params.build_targets,
        params.version,
    ]

    result_params = [
        results.manifest_set_key_result,
    ]

    step = tkn.model.TaskStep(
        name='finalise-promotion-step',
        image='$(params.step_image)',
        script=task_step_script(
            path=os.path.join(steps_dir, 'promote_step.py'),
            script_type=ScriptType.PYTHON3,
            callable='promote_step',
            params=step_params,
            results=result_params,
            repo_path_param=params.repo_dir,
        ),
        volumeMounts=volume_mounts,
        env=env_vars,
    )
    return step, step_params


def pre_build_step(
    params: params.AllParams,
    env_vars: typing.List[typing.Dict] = [],
    volume_mounts: typing.List[typing.Dict] = [],
):
    step_params = [
        params.architecture,
        params.cicd_cfg_name,
        params.committish,
        params.gardenlinux_epoch,
        params.modifiers,
        params.platform,
        params.build_targets,
        params.version,
    ]
    step = tkn.model.TaskStep(
        name='prebuild-step',
        image='$(params.step_image)',
        script=task_step_script(
            path=os.path.join(steps_dir, 'pre_build_step.py'),
            script_type=ScriptType.PYTHON3,
            callable='pre_build_step',
            params=step_params,
            repo_path_param=params.repo_dir,
        ),
        volumeMounts=volume_mounts,
        env=env_vars,
    )
    return step, step_params


def release_step(
    params: params.AllParams,
    env_vars: typing.List[typing.Dict] = [],
    volume_mounts: typing.List[typing.Dict] = [],
):
    step_params = [
        params.build_targets,
        params.cicd_cfg_name,
        params.committish,
        params.ctx_repository_config_name,
        params.flavour_set_name,
        params.gardenlinux_epoch,
        params.giturl,
        params.repo_dir,
        params.version,
    ]
    step = tkn.model.TaskStep(
        name='release-step',
        image='$(params.step_image)',
        script=task_step_script(
            path=os.path.join(steps_dir, 'release_step.py'),
            script_type=ScriptType.PYTHON3,
            callable='release_step',
            params=step_params,
            repo_path_param=params.repo_dir,
        ),
        volumeMounts=volume_mounts,
        env=env_vars,
    )
    return step, step_params


def create_component_descriptor_step(
    params: params.AllParams,
    env_vars: typing.List[typing.Dict] = [],
    volume_mounts: typing.List[typing.Dict] = [],
):
    step_params = [
        params.branch,
        params.build_targets,
        params.cicd_cfg_name,
        params.gardenlinux_committish,
        params.ctx_repository_config_name,
        params.flavour_set_name,
        params.gardenlinux_epoch,
        params.snapshot_ctx_repository_config_name,
        params.version,
    ]
    step = tkn.model.TaskStep(
        name='component-descriptor',
        image='$(params.step_image)',
        script=task_step_script(
            path=os.path.join(steps_dir, 'component_descriptor.py'),
            script_type=ScriptType.PYTHON3,
            callable='build_component_descriptor',
            repo_path_param=params.repo_dir,
            params=step_params,
        ),
        volumeMounts=volume_mounts,
        env=env_vars,
    )
    return step, step_params


def notify_step(
    params: params.AllParams,
    env_vars: typing.List[typing.Dict] = [],
    volume_mounts: typing.List[typing.Dict] = [],
):
    step_params = [
        params.additional_recipients,
        params.branch,
        params.cicd_cfg_name,
        params.committish,
        params.disable_notifications,
        params.giturl,
        params.namespace,
        params.only_recipients,
        params.pipeline_name,
        params.pipeline_run_name,
        params.repo_dir,
        params.status_dict_str,
    ]
    step = tkn.model.TaskStep(
        name='notify-status',
        image='$(params.step_image)',
        script=task_step_script(
            path=os.path.join(steps_dir, 'notify.py'),
            script_type=ScriptType.PYTHON3,
            callable='send_notification',
            repo_path_param=params.repo_dir,
            params=step_params,
        ),
        volumeMounts=volume_mounts,
        env=env_vars,
    )
    return step, step_params


def get_logs_step(
    params: params.AllParams,
    env_vars: typing.List[typing.Dict] = [],
    volume_mounts: typing.List[typing.Dict] = [],
):
    step_params = [
        params.repo_dir,
        params.pipeline_run_name,
        params.namespace,
    ]
    step = tkn.model.TaskStep(
        name='get-logs',
        image='$(params.step_image)',
        script=task_step_script(
            path=os.path.join(steps_dir, 'get_logs.py'),
            script_type=ScriptType.PYTHON3,
            callable='getlogs',
            repo_path_param=params.repo_dir,
            params=step_params,
        ),
        volumeMounts=volume_mounts,
        env=env_vars,
    )
    return step, step_params


def pre_check_tests_step(
    params: params.AllParams,
    env_vars: typing.List[typing.Dict] = [],
    volume_mounts: typing.List[typing.Dict] = [],
):
    step_params = [
        params.architecture,
        params.cicd_cfg_name,
        params.committish,
        params.gardenlinux_epoch,
        params.modifiers,
        params.platform,
        params.build_targets,
        params.version,
    ]
    step = tkn.model.TaskStep(
        name='pre-check-tests',
        image='$(params.step_image)',
        script=task_step_script(
            path=os.path.join(steps_dir, 'pre_check_tests.py'),
            script_type=ScriptType.PYTHON3,
            callable='pre_check_tests',
            repo_path_param=params.repo_dir,
            params=step_params,
        ),
        volumeMounts=volume_mounts,
        env=env_vars,
    )
    return step, step_params


def test_step(
    params: params.AllParams,
    env_vars: typing.List[typing.Dict] = [],
    volume_mounts: typing.List[typing.Dict] = [],
):
    step_params = [
        params.architecture,
        params.cicd_cfg_name,
        params.committish,
        params.gardenlinux_epoch,
        params.modifiers,
        params.platform,
        params.build_targets,
        params.repo_dir,
        params.snapshot_timestamp,
        params.suite,
        params.version,
        params.pytest_cfg,
    ]
    step = tkn.model.TaskStep(
        name='run-tests',
        image='$(params.step_image)',
        script=task_step_script(
            path=os.path.join(steps_dir, 'run_tests.py'),
            script_type=ScriptType.PYTHON3,
            callable='run_tests',
            repo_path_param=params.repo_dir,
            params=step_params,
        ),
        volumeMounts=volume_mounts,
        env=env_vars,
    )
    return step, step_params


def upload_test_results_step(
    params: params.AllParams,
    env_vars: typing.List[typing.Dict] = [],
    volume_mounts: typing.List[typing.Dict] = [],
):
    step_params = [
        params.architecture,
        params.cicd_cfg_name,
        params.committish,
        params.gardenlinux_epoch,
        params.modifiers,
        params.platform,
        params.build_targets,
        params.repo_dir,
        params.version,
    ]
    step = tkn.model.TaskStep(
        name='upload-test-results',
        image='$(params.step_image)',
        script=task_step_script(
            path=os.path.join(steps_dir, 'upload_test_results.py'),
            script_type=ScriptType.PYTHON3,
            callable='upload_test_results',
            repo_path_param=params.repo_dir,
            params=step_params,
        ),
        volumeMounts=volume_mounts,
        env=env_vars,
    )
    return step, step_params


def attach_log_step(
        params: params.AllParams,
        env_vars: typing.List[typing.Dict] = [],
        volume_mounts: typing.List[typing.Dict] = [],
    ):
    step_params = [
        params.architecture,
        params.build_tasks,
        params.build_targets,
        params.cicd_cfg_name,
        params.committish,
        params.flavour_set_name,
        params.gardenlinux_epoch,
        params.namespace,
        params.pipeline_run_name,
        params.platform_set,
        params.repo_dir,
        params.version,
]
    step = tkn.model.TaskStep(
        name='upload-logs-step',
        image='$(params.step_image)',
        script=task_step_script(
            path=os.path.join(steps_dir, 'attach_logs.py'),
            script_type=ScriptType.PYTHON3,
            callable='upload_logs',
            repo_path_param=params.repo_dir,
            params=step_params,
        ),
    volumeMounts=volume_mounts,
    env=env_vars,
    )
    return step, step_params