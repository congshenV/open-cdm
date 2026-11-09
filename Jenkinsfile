// Build the CloudDM console, sidecar and dmops Docker images and push them to
// an Aliyun ACR registry.
//
// The builder agent is itself a container (often with only an old JVM),
// so we do NOT rely on the agent's own toolchain. Instead the whole build
// chain runs inside a dedicated build image (package/docker/build-env.Dockerfile)
// that provides JDK 17, Node 22, Docker CLI + buildx. The agent only:
//   1. builds the build-env image,
//   2. runs package/docker/ci-run.sh inside it, which compiles, packages,
//      builds docker images and tags/pushes to ACR. The host docker socket
//      and ACR config.json are mounted so buildx/push reuse the host daemon.
//
// Builder agent prerequisites:
//   - docker (agent is a docker-in-docker or socket-mounted container)
//     NOTE: because the agent is dind, do NOT bind-mount the workspace by host
//     path into the build container - the outer daemon would resolve it on the
//     host where it does not exist. ci-run-docker.sh streams it in instead.
//   - ACR credentials in ~/.docker/config.json on the agent.
// The build itself (compile/tgz/docker) does not connect to a database; MySQL
// is only a runtime requirement of CloudDM, not a build-time one.

pipeline {
    agent { label 'agent-hk-1' }   // TODO: replace with your builder label

    options {
        timestamps()
        timeout(time: 120, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '20'))
        disableConcurrentBuilds()
    }

    environment {
        BUILD_IMAGE  = 'cgdm-build-env:ci'
        ACR          = 'maas-registry-vpc.cn-shanghai.cr.aliyuncs.com'
        NAMESPACE    = 'ack'                          // TODO: your ACR namespace
        SERVICES     = 'console sidecar dmops'
        BUILD_ARCH   = 'x86_64'
    }

    stages {
        stage('Setup') {
            steps {
                script {
                    env.BUILD_VERSION = sh(
                        returnStdout: true,
                        script: 'grep "^cg\\.clouddm\\.main\\.version=" backend/gradle.properties | cut -d= -f2 | tr -d "[:space:]"'
                    ).trim()
                    env.IMAGE_TAG = sh(
                        returnStdout: true,
                        script: 'echo "$(date +%Y%m%d)-$(git rev-parse --short HEAD)"'
                    ).trim()

                    echo """
=========================================
Build CloudDM console, sidecar & dmops
=========================================
Build version: ${env.BUILD_VERSION}
Image tag:     ${env.IMAGE_TAG}
Target:        ${env.ACR}/${env.NAMESPACE}
Branches:      ${env.GIT_BRANCH ?: 'detached'}
Commit:        ${env.GIT_COMMIT ?: 'unknown'}
"""
                }
            }
        }

        // The agent may only have an old JVM, so we build our own build image
        // once and run the entire chain inside it.
        stage('Prepare Build Image') {
            steps {
                script {
                    sh 'cd package/docker && docker build -f build-env.Dockerfile -t cgdm-build-env:ci .'
                }
            }
        }

        stage('Compile, Package, Build & Push') {
            steps {
                script {
                    withEnv([
                        'BUILD_ARCH=' + env.BUILD_ARCH,
                        'BUILD_VERSION=' + env.BUILD_VERSION,
                        'IMAGE_TAG=' + env.IMAGE_TAG,
                        'ACR=' + env.ACR,
                        'NAMESPACE=' + env.NAMESPACE,
                        'SERVICES=' + env.SERVICES
                    ]) {
                        sh 'cd package/docker && bash ci-run-docker.sh'
                    }
                }
            }
        }
    }

    post {
        success {
            script {
                def lines = env.SERVICES.tokenize().collect {
                    "  ${env.ACR}/${env.NAMESPACE}/cgdm-${it}:${env.IMAGE_TAG}"
                }.join('\n')
                echo """
===========================================
  CloudDM images built and pushed
===========================================
Images:
${lines}
Tag:   ${env.IMAGE_TAG}
"""
            }
        }
        failure {
            echo '==========================================='
            echo '  Build failed'
            echo '==========================================='
            echo 'Troubleshooting:'
            echo '  1. Agent needs docker (dind) + ACR creds in ~/.docker/config.json.'
            echo '  2. The build happens inside cgdm-build-env:ci (JDK17+Node22+buildx),'
            echo '     so the agent JVM version no longer matters.'
            echo '  3. No DB is needed at build time; MySQL is a runtime-only dependency.'
            echo '  4. Use ci-run-docker.sh (dind-ready) rather than manual -v bind mounts:'
            echo '       WORKSPACE=PWD BUILD_VERSION=x IMAGE_TAG=y ACR=z NAMESPACE=w \\'
            echo '       bash package/docker/ci-run-docker.sh'
        }
    }
}
