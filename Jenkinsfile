// Build the CloudDM console and sidecar Docker images and push them to
// an Aliyun ACR registry.
//
// Images are produced by the repo's own toolchain, not a hand-rolled build:
//   - `package/package.sh --build`  compiles backend + frontend and emits the tgz
//     payloads (`package/build/cgdm-{console,sidecar,alone}.tar.gz`).
//   - `package/package.sh --docker x86_64` then runs `package/docker/build-docker.sh`,
//     which builds each image with the matching `package/docker/{service}.Dockerfile`
//     (so console.Dockerfile / sidecar.Dockerfile are used) using the `shared/`
//     content as the build context.
// This Jenkinsfile only composes that chain and pushes the console+sidecar results.
//
// Builder agent prerequisites:
//   - docker + buildx, JDK 17+, Gradle 9.5+, Node 22 (backend + frontend build)
//   - a reachable dev MySQL 8 (package.sh --build needs it for an init-time check)
//   - ACR credentials in ~/.docker/config.json on the agent (docker login once)

pipeline {
    agent { label 'agent-hk-1' }   // TODO: replace with your builder label

    options {
        timestamps()
        timeout(time: 120, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '20'))
        disableConcurrentBuilds()
    }

    environment {
        ACR          = 'rmain-registry.cn-beijing.cr.aliyuncs.com'   // TODO: your ACR endpoint
        NAMESPACE    = 'ack'                          // TODO: your ACR namespace
        SERVICES     = 'console sidecar'
        BUILD_ARCH   = 'x86_64'
    }

    stages {
        stage('Setup') {
            steps {
                script {
                    // Same version the repo's own packaging uses (package.sh reads it too).
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
Build CloudDM console & sidecar
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

        stage('Compile & Package') {
            steps {
                script {
                    // Emits package/build/cgdm-{console,sidecar,alone}.tar.gz.
                    sh 'cd package && ./package.sh --build'
                }
            }
        }

        stage('Build Docker Images') {
            steps {
                script {
                    // Runs docker/build-docker.sh; builds console.Dockerfile / sidecar.Dockerfile
                    // (and alone.Dockerfile) via buildx. Local tags are:
                    //   clougence/cgdm-{svc}:${BUILD_ARCH}-${BUILD_VERSION}
                    sh 'cd package && ./package.sh --docker ${BUILD_ARCH}'
                }
            }
        }

        stage('Tag & Push (console, sidecar)') {
            steps {
                script {
                    SERVICES_LIST = env.SERVICES.tokenize()
                    for (svc in SERVICES_LIST) {
                        def src = "clougence/cgdm-${svc}:${env.BUILD_ARCH}-${env.BUILD_VERSION}"
                        def dst = "${env.ACR}/${env.NAMESPACE}/cgdm-${svc}:${env.IMAGE_TAG}"
                        sh """
                            set -euo pipefail
                            echo "Tagging  \${src} -> \${dst}"
                            docker tag \${src} \${dst}
                            echo "Pushing  \${dst}"
                            docker push \${dst}
                            echo "Pushed:  \${dst}"
                        """
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
  Console & sidecar built and pushed
===========================================
Images:
${lines}
Tag:   ${env.IMAGE_TAG}
"""
            }
        }
        failure {
            echo """
===========================================
  Build failed
===========================================
Troubleshooting:
  1. Builder must have docker + buildx, JDK 17+, Gradle 9.5+, Node 22,
     and reachable dev MySQL 8.
  2. Confirm builder is logged into the ACR (~/.docker/config.json).
  3. package.sh --build compiles backend + frontend first; a build error
     in the backend (gradle) or frontend (npm) will fail here.
  4. Re-run locally: cd package && ./package.sh --build --docker x86_64
"""
        }
        always {
            cleanWs()
        }
    }
}
