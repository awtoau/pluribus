prj_project new -name "v07" -impl "impl1" -dev LCMXO2-1200HC-5TG100C -synthesis "lse"
prj_src add "v07_core.v"
prj_run Synthesis -impl impl1
prj_project close
