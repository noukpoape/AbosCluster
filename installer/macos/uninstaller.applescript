-- Désinstaller AbosCluster : supprime /Applications/AbosCluster et les préférences.
-- Les projets et les données de l'utilisateur ne sont jamais supprimés.
-- Compilé en application par build_pkg.sh (osacompile).

set enFrancais to (user locale of (system info)) starts with "fr"
if enFrancais then
	set texteConfirmer to "Voulez-vous désinstaller AbosCluster ?" & return & return & "Vos projets et vos données ne seront pas supprimés."
	set texteFermer to "AbosCluster est ouvert. Fermez-le (après avoir enregistré votre projet), puis cliquez sur Réessayer."
	set texteFin to "AbosCluster a été désinstallé."
	set texteErreur to "La désinstallation a échoué :"
	set boutonAnnuler to "Annuler"
	set boutonDesinstaller to "Désinstaller"
	set boutonReessayer to "Réessayer"
else
	set texteConfirmer to "Do you want to uninstall AbosCluster?" & return & return & "Your projects and data will not be deleted."
	set texteFermer to "AbosCluster is running. Close it (after saving your project), then click Retry."
	set texteFin to "AbosCluster has been uninstalled."
	set texteErreur to "Uninstallation failed:"
	set boutonAnnuler to "Cancel"
	set boutonDesinstaller to "Uninstall"
	set boutonReessayer to "Retry"
end if

try
	display dialog texteConfirmer buttons {boutonAnnuler, boutonDesinstaller} default button boutonDesinstaller cancel button boutonAnnuler with title "AbosCluster" with icon caution
on error number -128
	return
end try

-- l'application doit etre fermee
repeat while (do shell script "pgrep -f [/]Applications/AbosCluster/AbosCluster.app/Contents/MacOS/AbosCluster >/dev/null && echo oui || echo non") is "oui"
	try
		display dialog texteFermer buttons {boutonAnnuler, boutonReessayer} default button boutonReessayer cancel button boutonAnnuler with title "AbosCluster" with icon caution
	on error number -128
		return
	end try
end repeat

try
	-- mot de passe administrateur demande par macOS
	do shell script "rm -rf '/Applications/AbosCluster'; pkgutil --forget fr.inria.aboscluster >/dev/null 2>&1; exit 0" with administrator privileges
on error messageErreur number numero
	if numero is -128 then return
	display dialog texteErreur & return & messageErreur buttons {"OK"} default button "OK" with title "AbosCluster" with icon stop
	return
end try

-- preferences de l'utilisateur (langue, police, filtres, graphiques)
do shell script "rm -f \"$HOME/.abos_preferences.json\" \"$HOME/.abos_filtres.json\" \"$HOME/.abos_parametres_graphiques.json\""

display dialog texteFin buttons {"OK"} default button "OK" with title "AbosCluster" with icon note
