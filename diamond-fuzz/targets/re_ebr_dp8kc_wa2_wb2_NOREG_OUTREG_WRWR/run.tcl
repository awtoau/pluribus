prj_project open "[file normalize [file join [file dirname [info script]] fuzz.ldf]]"
prj_run PAR    -impl impl1
prj_run Export -impl impl1 -task Bitgen
prj_project close
