# Gardenlinux image publishing gear

This repository contains tooling and configuration for publishing gardenlinux images as machine
images to different hyperscalers.

The images to be published are built in a separate pipeline from sources hosted in
[gardenlinux repository](https://github.com/gardenlinux/gardenlinux), and consumed from a
S3 bucket.

The publishing gear is intended to be run on a Tekton installation.

## Installation


Follow instructions to install

- [tekton pipelines](https://github.com/tektoncd/pipeline)
- [tekton dashboard](https://github.com/tektoncd/dashboard)

Known good versions:

- v0.25.0 (pipeliens)
- v0.18.0 (dashboard)


### Local Setup (for development/testing/debugging)

- tekton-cli
- python3.9 or greater
- install packages from ci/images/step_image/requirements.txt
- kubectl



### Grant API Permissions To Script User

All tekton related scripts are executed by a service user "default" in the corresponding namespace. This user must be granted the permission to get (read) access to Tekton and pod resources:

```
kind: ClusterRole
apiVersion: rbac.authorization.k8s.io/v1
metadata:
  name: incluster-tektonaccess
rules:
- apiGroups: ["tekton.dev"]
  resources: ["*"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["pods", "pods/log"]
  verbs: ["get", "list", "watch"]
---
kind: ClusterRoleBinding
apiVersion: rbac.authorization.k8s.io/v1
metadata:
  name: incluster-tektonaccess-gardenlinux
subjects:
- kind: ServiceAccount
  name: default
  namespace: gardenlinux
roleRef:
  kind: ClusterRole
  name: incluster-tektonaccess
  apiGroup: rbac.authorization.k8s.io
---
kind: ClusterRoleBinding
apiVersion: rbac.authorization.k8s.io/v1
metadata:
  name: incluster-tektonaccess-jens
subjects:
- kind: ServiceAccount
  name: default
  namespace: jens
roleRef:
  kind: ClusterRole
  name: incluster-tektonaccess
  apiGroup: rbac.authorization.k8s.io
```

### Namespace:

The namespace can be set according to your preferences. In this document and in the provided scripts the namespace "gardenlinux" is used. The namespace is set in an environment variable "GARDENLINUX_TKN_WS". If not set it defaults to "gardenlinux"

## Overview About The Build


Build variants:
The build can handle various variants of build artifacts. These are configured by a flavour set. The flavours are defined in the file flavours.yaml in the root directory of th Git repository. By default there is one set in this file named "all". You can add more sets according to your needs.

Build-Target:
There are options how the build artifacts are handled after build. This is set in the environment variable BUILD_TARGETS (see also class BuildTarget in ci/glci/model.py). Currently there are four variants supported:

 - `build`
 - `manifest`
 - `release`
 - `publish`

If the variable is not set it defaults to "`build`"

The flavour set build by the pipeline is contained in the environment variable
FLAVOUR_SET and defaults to "all" if not set.

**Example:**
Here is example to build only the AWS image. Append the following snippet to `flavours.yaml`:

```
  - name: 'aws'
    flavour_combinations:
      - architectures: [ 'amd64' ]
        platforms: [ aws ]
        modifiers: [ [ _prod, gardener ] ]
        fails: [ unit, integration ]

```

### Environment Variables
The script to generate the pipeline definitions reads various environment variables. These variables can be set to control the configuration. See also file [ci/lib.sh](lib.sh). Here is an example:

```
# Namespace where pipelines are deployed defaults to "gardenlinux":
export GARDENLINUX_TKN_WS=gardenlinux
# type of artifacts to be built:
export BUILD_TARGETS=manifests
# build variant: defaults to "all"
export FLAVOUR_SET=all
# Git branch to build, defaults to "main"
export BRANCH_NAME=main
# path to upload base images in container registry
export OCI_PATH=eu.gcr.io/gardener-project/test/gardenlinux-test
# Repository in Git:
export GIT_URL=https://github.com/gardenlinux/gardenlinux
# secret encryption, set algorithm to "PLAINTEXT"
export SECRET_CIPHER_ALGORITHM=PLAINTEXT
```

### Creating and running the pipelines

Run the script to generate and apply the pipelines:

`ci/render_pipelines_and_trigger_job`

This script creates several yaml files containing the Tekton definitions for the gardenlinux build. They are applied automatically to the target cluster described by your `KUBECONFIG` environment variable.

This script has the following parameters:

* `--image-build`: Build Garden Linux
* `--wait`: The script terminates when pipeline run is finished

Example:

`ci/render_pipelines_and_trigger_job --image-build`


### Credential Handling

The build pipeline can be used with a central server managing configuration and
secrets. As an alternative all credentials can be read from a Kubernetes secret
named "secrets" in the corresponding namespace. This secret will be
automatically generated from configuration files. The switch between central
server and a Kubernetes secret is done by an environment variable named
`SECRET_SERVER_ENDPOINT`. If it is not set the secret will be generated and
applied. At minimum there need to be two secrets: One for uploading the
artifacts to an S3-like Object store and one to upload container images to an
OCI registry. Example files are provided in the folder `ci/cfg`.

Edit the files cfg/cfg_types.yaml. Each top-level entry refers to another file
containing the credentials. Examples with templates are provided. A second
entry is for uploading the base-image and to an OCI registry. Additional
configuration information is found in [cicd.yaml](cicd.yaml)

For sending notifications by default recipients are read from the CODEOWNERS
files. Resolving this to email requires access to the Github API which is not
possible for external users. The behavior can be overriden by setting the
variable `only_recipients` in the pipelineRun file. If this variable contains a
semicolon separated list of email addresses emails are sent only to these
recipients. CODEWONWERS access is not needed then. For configuring an SMTP
server a sample file is provided.


## Integration Tests (under construction)

The integration test are implemented as their own tekton task which can be
found [here](./integrationtest-task.yaml).  The test automatically clones the
github repo specified in the tekton resource and executes the integration test
with the specified version (branch or commit).

The task assumes that there is a secret in the cluster with the following
structure:

```yaml
---
apiVersion: v1
kind: Secret
metadata:
  name: github-com-user
  annotations:
    tekton.dev/git-0: https://github.com
type: kubernetes.io/basic-auth
stringData:
  username: <github username>
  password: <github password>
```

The test can be executed within a cluster that has tekton installed by running:

```
# create test defintions and resources
kubectl apply -f ./ci/integrationtest-task.yaml

# run the actual test as taskrun
kubectl create -f ./ci/it-run.yaml
```
Running the integration tests is work-in-progress.
