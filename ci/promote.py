#!/usr/bin/env python3

'''
Promotes the specified build results (represented by build result manifests in S3).

An example being the promotion of a build snapshot to a daily build.
'''

import argparse
import concurrent.futures
import functools
import logging
import logging.config
import os
import sys
import typing

import glci.util
import glci.model
import version

glci.util.configure_logging()

logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--flavourset', default='all')
    parser.add_argument('--committish')
    parser.add_argument('--gardenlinux-epoch', type=int)
    parser.add_argument(
        '--build-targets',
        type=lambda x: (glci.model.BuildTarget(v) for v in x.split(',')),
        action='extend',
        dest='build_targets',
    )
    parser.add_argument('--version', required=True)
    parser.add_argument('--source', default='snapshots')
    parser.add_argument(
        '--target',
        type=glci.model.BuildType,
        default=glci.model.BuildType.SNAPSHOT
    )
    parser.add_argument('--cicd-cfg', default='default')
    parser.add_argument('--allow-partial', default=False, action='store_true')
    parser.add_argument('--azure-sig',
        default=False,
        action='store_true',
        help='Test Azure Shared Image Gallery'
    )

    return parser.parse_args()


def publish_image(
    release: glci.model.OnlineReleaseManifest,
    cicd_cfg: glci.model.CicdCfg,
) -> glci.model.OnlineReleaseManifest:
    logger.info(f'running release for {release.platform=}')

    if release.platform == 'ali':
        publish_function = _publish_alicloud_image
        cleanup_function = _clean_alicloud_image
    elif release.platform == 'aws':
        publish_function = _publish_aws_image
        cleanup_function = _cleanup_aws
    elif release.platform == 'gcp':
        publish_function = _publish_gcp_image
        cleanup_function = None
    elif release.platform == 'azure':
        if cicd_cfg.publish.azure.shared_gallery_cfg_name:
            publish_function = _publish_azure_shared_image_gallery
        else:
            publish_function = _publish_azure_image
        cleanup_function = None
    elif release.platform == 'openstack':
        publish_function = _publish_openstack_image
        cleanup_function = _cleanup_openstack_image
    elif release.platform == 'oci':
        publish_function = _publish_oci_image
        cleanup_function = None
    else:
        logger.warning(f'do not know how to publish {release.platform=}, yet')
        return release

    try:
        return publish_function(release, cicd_cfg)
    except:
        import traceback
        traceback.print_exc()
        if not cleanup_function is None:
            cleanup_function(release, cicd_cfg)
        else:
            logger.warning(f'do not know how to cleanup {release.platform=}')
        raise


def _publish_alicloud_image(release: glci.model.OnlineReleaseManifest,
                            cicd_cfg: glci.model.CicdCfg,
) -> glci.model.OnlineReleaseManifest:
    import ccc.alicloud
    import glci.model
    import glci.alicloud
    build_cfg = cicd_cfg.build
    alicloud_cfg_name = build_cfg.alicloud_cfg_name

    oss_auth = ccc.alicloud.oss_auth(alicloud_cfg=alicloud_cfg_name)
    acs_client = ccc.alicloud.acs_client(alicloud_cfg=alicloud_cfg_name)

    maker = glci.alicloud.AlicloudImageMaker(
        oss_auth, acs_client, release, cicd_cfg.build)

    import ccc.aws
    s3_client = ccc.aws.session(cicd_cfg.build.aws_cfg_name).client('s3')
    maker.cp_image_from_s3(s3_client)
    return maker.make_image()


def _clean_alicloud_image(release: glci.model.OnlineReleaseManifest,
                            cicd_cfg: glci.model.CicdCfg,
) -> glci.model.OnlineReleaseManifest:
    import ccc.alicloud
    import glci.model
    import glci.alicloud
    build_cfg = cicd_cfg.build
    alicloud_cfg_name = build_cfg.alicloud_cfg_name

    oss_auth = ccc.alicloud.oss_auth(alicloud_cfg=alicloud_cfg_name)
    acs_client = ccc.alicloud.acs_client(alicloud_cfg=alicloud_cfg_name)

    maker = glci.alicloud.AlicloudImageMaker(
        oss_auth, acs_client, release, cicd_cfg.build)

    return maker.delete_images()


def _publish_aws_image(release: glci.model.OnlineReleaseManifest,
                       cicd_cfg: glci.model.CicdCfg,
) -> glci.model.OnlineReleaseManifest:
    import glci.aws
    return glci.aws.upload_and_register_gardenlinux_image(
        publish_cfg=cicd_cfg.publish.aws,
        release=release,
    )


def _cleanup_aws(
    release: glci.model.OnlineReleaseManifest,
    cicd_cfg: glci.model.CicdCfg,
):
    import glci.aws
    import ccc.aws
    target_image_name = glci.aws.target_image_name_for_release(release=release)
    for aws_cfg_name in cicd_cfg.publish.aws.aws_cfg_names:
        mk_session = functools.partial(ccc.aws.session, aws_cfg=aws_cfg_name)
        glci.aws.unregister_images_by_name(
            mk_session=mk_session,
            image_name=target_image_name,
        )


def _publish_azure_image(release: glci.model.OnlineReleaseManifest,
                       cicd_cfg: glci.model.CicdCfg,
                       ) -> glci.model.OnlineReleaseManifest:
    import glci.az
    import glci.model
    import ccc.aws
    import ci.util

    s3_client = ccc.aws.session(cicd_cfg.build.aws_cfg_name).client('s3')
    cfg_factory = ci.util.ctx().cfg_factory()

    service_principal_cfg = cfg_factory.azure_service_principal(
        cicd_cfg.publish.azure.service_principal_cfg_name
    )
    service_principal_cfg_serialized = glci.model.AzureServicePrincipalCfg(
        tenant_id=service_principal_cfg.tenant_id(),
        client_id=service_principal_cfg.client_id(),
        client_secret=service_principal_cfg.client_secret(),
        subscription_id=service_principal_cfg.subscription_id(),
    )
    storage_account_cfg = cfg_factory.azure_storage_account(
        cicd_cfg.publish.azure.storage_account_cfg_name
    )
    storage_account_cfg_serialized = glci.model.AzureStorageAccountCfg(
        storage_account_name=storage_account_cfg.storage_account_name(),
        access_key=storage_account_cfg.access_key(),
        container_name=storage_account_cfg.container_name(),
        container_name_sig=storage_account_cfg.container_name_sig(),
    )

    azure_marketplace_cfg = glci.model.AzureMarketplaceCfg(
        publisher_id=cicd_cfg.publish.azure.publisher_id,
        offer_id=cicd_cfg.publish.azure.offer_id,
        plan_id=cicd_cfg.publish.azure.plan_id,
    )

    return glci.az.upload_and_publish_image(
        s3_client,
        service_principal_cfg=service_principal_cfg_serialized,
        storage_account_cfg=storage_account_cfg_serialized,
        marketplace_cfg=azure_marketplace_cfg,
        release=release,
        notification_emails=cicd_cfg.publish.azure.notification_emails,
    )


def _publish_azure_shared_image_gallery(
    release: glci.model.OnlineReleaseManifest,
    cicd_cfg: glci.model.CicdCfg,
) -> str:
    import glci.az
    import glci.model
    import ccc.aws
    import ci.util

    s3_client = ccc.aws.session(cicd_cfg.build.aws_cfg_name).client('s3')
    cfg_factory = ci.util.ctx().cfg_factory()

    storage_account_cfg = cfg_factory.azure_storage_account(
        cicd_cfg.publish.azure.storage_account_cfg_name
    )
    storage_account_cfg_serialized = glci.model.AzureStorageAccountCfg(
        storage_account_name=storage_account_cfg.storage_account_name(),
        access_key=storage_account_cfg.access_key(),
        container_name=storage_account_cfg.container_name(),
        container_name_sig=storage_account_cfg.container_name_sig(),
    )
    # get credential object from configured user and secret
    azure_principal = cfg_factory.azure_service_principal(
        cfg_name=cicd_cfg.publish.azure.service_principal_cfg_name
    )
    azure_principal_serialized =  glci.model.AzureServicePrincipalCfg(
        tenant_id=azure_principal.tenant_id(),
        client_id=azure_principal.client_id(),
        client_secret=azure_principal.client_secret(),
        subscription_id=azure_principal.subscription_id(),
    )

    shared_gallery_cfg = cfg_factory.azure_shared_gallery(
        cfg_name=cicd_cfg.publish.azure.shared_gallery_cfg_name
    )
    shared_gallery_cfg_serialized = glci.model.AzureSharedGalleryCfg(
        resource_group_name=shared_gallery_cfg.resource_group_name(),
        gallery_name=shared_gallery_cfg.gallery_name(),
        location=shared_gallery_cfg.location(),
        published_name=shared_gallery_cfg.published_name(),
        description=shared_gallery_cfg.description(),
        eula=shared_gallery_cfg.eula(),
        release_note_uri=shared_gallery_cfg.release_note_uri(),
        identifier_publisher=shared_gallery_cfg.identifier_publisher(),
        identifier_offer=shared_gallery_cfg.identifier_offer(),
        identifier_sku=shared_gallery_cfg.identifier_sku(),
    )

    return glci.az.publish_azure_shared_image_gallery(
        s3_client=s3_client,
        release=release,
        service_principal_cfg=azure_principal_serialized,
        storage_account_cfg=storage_account_cfg_serialized,
        shared_gallery_cfg=shared_gallery_cfg_serialized,
    )


def _publish_gcp_image(release: glci.model.OnlineReleaseManifest,
                       cicd_cfg: glci.model.CicdCfg,
                       ) -> glci.model.OnlineReleaseManifest:
    import glci.gcp
    import ccc.aws
    import ccc.gcp
    import ci.util
    gcp_cfg = ci.util.ctx().cfg_factory().gcp(cicd_cfg.build.gcp_cfg_name)
    storage_client = ccc.gcp.cloud_storage_client(gcp_cfg)
    s3_client = ccc.aws.session(cicd_cfg.build.aws_cfg_name).client('s3')
    compute_client = ccc.gcp.authenticated_build_func(gcp_cfg)('compute', 'v1')
    return glci.gcp.upload_and_publish_image(
        storage_client=storage_client,
        s3_client=s3_client,
        compute_client=compute_client,
        gcp_project_name=gcp_cfg.project(),
        release=release,
        build_cfg=cicd_cfg.build,
    )


def _publish_oci_image(
    release: glci.model.OnlineReleaseManifest,
    cicd_cfg: glci.model.CicdCfg,
    release_build: bool = True,
) -> glci.model.OnlineReleaseManifest:
    import ccc.aws
    import glci.oci
    import ccc.oci

    oci_client = ccc.oci.oci_client()
    s3_client = ccc.aws.session(cicd_cfg.build.aws_cfg_name).client('s3')

    return glci.oci.publish_image(
        release=release,
        publish_cfg=cicd_cfg.publish.oci,
        s3_client=s3_client,
        oci_client=oci_client,
        release_build=release_build,
    )


def _publish_openstack_image(release: glci.model.OnlineReleaseManifest,
                       cicd_cfg: glci.model.CicdCfg,
                       ) -> glci.model.OnlineReleaseManifest:
    import glci.openstack_image
    import ccc.aws
    import ci.util

    s3_client = ccc.aws.session(cicd_cfg.build.aws_cfg_name).client('s3')
    cfg_factory = ci.util.ctx().cfg_factory()
    openstack_environments_cfg = cfg_factory.ccee(cicd_cfg.publish.openstack.environment_cfg_name)

    username = openstack_environments_cfg.credentials().username()
    password = openstack_environments_cfg.credentials().passwd()

    image_properties = cfg_factory._cfg_element(
        cfg_type_name='openstack_os_image',
        cfg_name=cicd_cfg.publish.openstack.image_properties_cfg_name,
    ).raw['properties']

    openstack_env_cfgs = tuple((
        glci.model.OpenstackEnvironment(
            project_name=project.name(),
            domain=project.domain(),
            region=project.region(),
            auth_url=project.auth_url(),
            username=username,
            password=password,
        ) for project in openstack_environments_cfg.projects()
    ))

    return glci.openstack_image.upload_and_publish_image(
        s3_client,
        openstack_environments_cfgs=openstack_env_cfgs,
        image_properties=image_properties,
        release=release,
    )


def _cleanup_openstack_image(
    release: glci.model.OnlineReleaseManifest,
    cicd_cfg: glci.model.CicdCfg,
):
    import glci.openstack_image
    import ci.util

    cfg_factory = ci.util.ctx().cfg_factory()
    openstack_environments_cfg = cfg_factory.ccee(cicd_cfg.publish.openstack.environment_cfg_name)

    username = openstack_environments_cfg.credentials().username()
    password = openstack_environments_cfg.credentials().passwd()

    openstack_env_cfgs = tuple((
        glci.model.OpenstackEnvironment(
            project_name=project.name(),
            domain=project.domain(),
            region=project.region(),
            auth_url=project.auth_url(),
            username=username,
            password=password,
        ) for project in openstack_environments_cfg.projects()
    ))

    glci.openstack_image.delete_images_for_release(
        openstack_environments_cfgs=openstack_env_cfgs,
        release=release,
    )


def distribute_artifacts(
    cicd_cfg: glci.model.CicdCfg,
):
    source_client = ccc.aws.session(cicd_cfg.build.aws_cfg_name).client('s3')