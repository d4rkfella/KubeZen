#!/usr/bin/env python3
import subprocess
from typing import List, Tuple, Optional
from .kube_base import KubeBase
import sys
import time

class PVCManager(KubeBase):
    resource_type = "persistentvolumeclaims"
    resource_name = "PersistentVolumeClaim"

    def _get_resource_fzf_elements(self) -> List[dict]:
        return [
            {"fzf_bind_action": "alt-f:accept", "header_text": "Alt-F: File Browser"},
        ]

    def _get_resource_actions(self):
        """Provide PVC-specific actions"""
        return {
            "alt-f": self.file_browser_pvc
        }

    def file_browser_pvc(self, pvc_name: str):
        subprocess.run(["clear"])
        print(f"Attempting to launch file browser for PVC '{pvc_name}' in namespace '{self.current_namespace}'...")

        try:
            while True:
                try:
                    user_input = input("\nEnter user ID to run the pod as (default: 65532): ").strip()
                    if not user_input:
                        user_id = 65532
                        break
                    try:
                        user_id = int(user_input)
                        if user_id < 0:
                            print("User ID must be a non-negative integer")
                            continue
                        if user_id > 65535:
                            print("User ID must be less than or equal to 65535")
                            continue
                        break
                    except ValueError:
                        print("Please enter a valid integer")
                except KeyboardInterrupt:
                    print("\nOperation cancelled by user.")
                    input("\nPress Enter to continue...")
                    return
        except KeyboardInterrupt:
            print("\nOperation cancelled by user.")
            input("\nPress Enter to continue...")
            return

        fb_pod_name = f"filebrowser-{pvc_name}"
        namespace = self.current_namespace
        deployment_successful = False

        try:
            existing_pod_spec = self.kubectl_client.get_resource_spec("pod", fb_pod_name, namespace)
            if existing_pod_spec:
                print(f"\nPod '{fb_pod_name}' already exists in namespace '{namespace}'.")
                response = input("Delete existing pod and proceed? (y/N): ").strip().lower()
                if response == 'y':
                    print(f"Deleting existing pod '{fb_pod_name}'...")
                    deleted, del_msg = self.kubectl_client.delete_resource("pod", fb_pod_name, namespace)
                    if not deleted:
                        print(f"Failed to delete pod: {del_msg}", file=sys.stderr)
                        input("\nPress Enter to continue...")
                        return
                    print(f"Pod '{fb_pod_name}' deleted. Waiting a moment before recreating...")
                    time.sleep(3)
                else:
                    print("Operation cancelled.")
                    input("\nPress Enter to continue...")
                    return
            
            print(f"\n🚀 Deploying File Browser pod '{fb_pod_name}' in namespace '{namespace}' with default credentials admin/admin...")
            print(f"Pod will run as user ID: {user_id}")

            run_cmd = [
                "kubectl", "run", fb_pod_name,
                "--image=filebrowser/filebrowser",
                "--restart=Never",
                f"--namespace={namespace}",
                f"--overrides={{\"spec\":{{\"hostUsers\":false,\"securityContext\":{{\"runAsNonRoot\":true,\"runAsUser\":{user_id},\"runAsGroup\":{user_id},\"fsGroup\":{user_id},\"seccompProfile\":{{\"type\":\"RuntimeDefault\"}}}},\"volumes\":[{{\"name\":\"target-pvc\",\"persistentVolumeClaim\":{{\"claimName\":\"{pvc_name}\"}}}},{{\"name\":\"fb-data\",\"emptyDir\":{{}}}}],\"containers\":[{{\"name\":\"fb\",\"image\":\"filebrowser/filebrowser\",\"args\":[\"--database\",\"/data/filebrowser.db\"],\"ports\":[{{\"containerPort\":80}}],\"volumeMounts\":[{{\"mountPath\":\"/srv\",\"name\":\"target-pvc\"}},{{\"mountPath\":\"/data\",\"name\":\"fb-data\"}}],\"securityContext\":{{\"readOnlyRootFilesystem\":true,\"allowPrivilegeEscalation\":false,\"capabilities\":{{\"drop\":[\"ALL\"]}}}}}}]}}}}"
            ]
            subprocess.run(run_cmd, check=True, capture_output=True, text=True)
            print(f"Pod '{fb_pod_name}' deployment initiated.")
            deployment_successful = True

            print("\n⏳ Waiting for pod to be ready...")
            ready, wait_msg = self.kubectl_client.wait_for_resource_ready(f"pod/{fb_pod_name}", namespace, timeout_seconds=120)
            print(wait_msg)
            if not ready:
                input("\nPress Enter to continue...")
                return

            print(f"Pod '{fb_pod_name}' is ready.")
            print("\n🌐 Starting port-forward to access File Browser UI at http://localhost:8080")
            print("Press Ctrl+C to stop the port-forward and clean up the pod.")
            
            port_forward_cmd = ["kubectl", "port-forward", f"pod/{fb_pod_name}", "8080:80", f"--namespace={namespace}"]
            try:
                subprocess.run(port_forward_cmd, check=True)
            except subprocess.CalledProcessError as pfe:
                 print(f"Error starting port-forward: {pfe.stderr.strip() if pfe.stderr else pfe.stdout.strip()}", file=sys.stderr)
            except KeyboardInterrupt:
                print("\nCtrl+C detected. Stopping port-forward and proceeding to cleanup...")

        except subprocess.CalledProcessError as e:
            subprocess.run(["clear"])
            error_output = e.stderr.strip() if e.stderr else e.stdout.strip()
            print(f"An error occurred: {error_output}", file=sys.stderr)
        except KeyboardInterrupt:
            print("\nOperation cancelled by user during setup.")
        finally:
            if deployment_successful:
                print("\n🧹 Cleaning up pod...")
                deleted, del_msg = self.kubectl_client.delete_resource("pod", fb_pod_name, namespace, grace_period=0)
                if deleted:
                    print(f"Pod '{fb_pod_name}' cleanup initiated.")
                else:
                    print(f"Warning: Failed to delete pod '{fb_pod_name}': {del_msg}", file=sys.stderr)
            else:
                print("\nSkipping cleanup as pod deployment was not successful or was cancelled prior.")
            input("\nPress Enter to continue...") 