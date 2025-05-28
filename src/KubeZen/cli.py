import click
from KubeZen.resources.kube_pods import PodManager
from KubeZen.resources.kube_services import ServiceManager
from KubeZen.resources.kube_deployments import DeploymentManager
from KubeZen.resources.kube_configmaps import ConfigMapManager
from KubeZen.resources.kube_secrets import SecretManager
from KubeZen.resources.kube_daemonsets import DaemonSetManager
from KubeZen.resources.kube_statefulsets import StatefulSetManager
from KubeZen.resources.kube_pvcs import PVCManager

@click.group()
def cli():
    """KubeZen: Kubernetes CLI tool for managing resources interactively."""
    pass

@cli.command()
def pods():
    """Manage Kubernetes pods."""
    manager = PodManager()
    manager.navigate()

@cli.command()
def services():
    """Manage Kubernetes services."""
    manager = ServiceManager()
    manager.navigate()

@cli.command()
def deployments():
    """Manage Kubernetes deployments."""
    manager = DeploymentManager()
    manager.navigate()

@cli.command()
def configmaps():
    """Manage Kubernetes configmaps."""
    manager = ConfigMapManager()
    manager.navigate()

@cli.command()
def secrets():
    """Manage Kubernetes secrets."""
    manager = SecretManager()
    manager.navigate()

@cli.command()
def daemonsets():
    """Manage Kubernetes daemonsets."""
    manager = DaemonSetManager()
    manager.navigate()

@cli.command()
def statefulsets():
    """Manage Kubernetes statefulsets."""
    manager = StatefulSetManager()
    manager.navigate()

@cli.command()
def pvcs():
    """Manage Kubernetes persistent volume claims."""
    manager = PVCManager()
    manager.navigate()

if __name__ == '__main__':
    cli() 