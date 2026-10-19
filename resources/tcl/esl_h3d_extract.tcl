# esl_h3d_extract.tcl -- HyperView batch extractor for the ESL core (contract: esl_core.md 3.2)
#
#   hw -clientconfig hwpost.dat -b -tcl esl_h3d_extract.tcl -input <h3d> -part <title|id> -output <dir> [-config <request.txt>]
#
# Writes into <dir>:
#   frames.csv  frame_index,time
#   model.csv   node_id,x0,y0,z0                         (target part nodes, first written frame)
#   strain.csv  frame_index,elem_id,layer,exx,eyy,exy    (layer = bottom|top[|mid], tensor shear)
#   disp.csv    frame_index,node_id,ux,uy,uz
#   done.json   {"ok":true,...}  or  {"ok":false,"code","error","failed_step","errorCode","errorInfo",
#               "steps_done","api","traces","env","components",...}   (ALWAYS written; if <dir> cannot
#               be written: stderr + esl_extract_done_fallback.json next to this script)
#
# Part: -part <id or title> > request.txt part_id > request.txt part_title. A title is matched
# against the h3d component names ignoring case, blanks and underscores ("Chassis Rear" ==
# "chassis_rear"). Without a part: done.json ok:false (INPUT_INVALID) with the component list.
#
# request.txt (OPTIONAL; missing -> defaults): one "key<TAB>value" per line, '#' lines ignored. Keys:
#   part_id, part_title, subcase (1), frame_stride (1), strain_type (Strain),
#   strain_comps (XX YY XY), layer_bottom (Lower), layer_top (Upper), layer_mid (empty = skip),
#   shear_is_engineering (0|1), disp_type (Displacement), disp_comps (X Y Z),
#   elem_selection / node_selection (optional HyperView selection string, e.g. "component 12"),
#   strain_system (elemental | analysis | global | none; default elemental).
#
# Existing outputs (done.json, *.csv) in <dir> are moved to <dir>/_backup/<timestamp>/ first
# (never deleted). All numbers are written with "format %.17g" (round-trip exact for doubles).
#
# NOT VERIFIED against a real HyperView installation (written from the hwi/poI* Tcl API docs).
# Run esl_h3d_probe.tcl first. This file is kept ASCII-only on purpose (Tcl source encoding).

# ---------------------------------------------------------------------------------------------
# Common block (kept identical in esl_h3d_probe.tcl and esl_h3d_extract.tcl so each file runs
# on its own): JSON helpers, step tracking, alternatives, environment, HyperView session open,
# component list and part resolution.
# ---------------------------------------------------------------------------------------------
namespace eval ::esl {
    variable warnings {}
    # step tracking: current step, finished steps, per-call status (name -> text), error traces
    variable cur_step "start"
    variable steps_done {}
    variable api [dict create]
    variable traces [dict create]
    variable env [dict create]
    variable comps {}
    variable comps_src ""
    variable sess ""
    variable outdir ""
    variable h3d ""
    # unique handle-name suffix: avoids "object with this name already exists" on re-runs
    variable sfx "[pid]_[expr {[clock clicks] & 0xffffff}]"
    variable script_dir ""
    catch {set script_dir [file dirname [file normalize [info script]]]}
}

proc ::esl::jstr {s} {
    set s [string map [list "\\" "\\\\" "\"" "\\\"" "\n" "\\n" "\r" "\\r" "\t" "\\t"] $s]
    # other control characters -> \u00XX
    set out ""
    foreach ch [split $s ""] {
        scan $ch %c c
        if {$c < 32} { append out [format "\\u%04x" $c] } else { append out $ch }
    }
    return "\"$out\""
}
proc ::esl::jarr {items} {
    set out {}
    foreach it $items { lappend out [::esl::jstr $it] }
    return "\[[join $out ,]\]"
}
proc ::esl::jobj {d} {
    set out {}
    dict for {k v} $d { lappend out "[::esl::jstr $k]:[::esl::jstr $v]" }
    return "\{[join $out ,]\}"
}
proc ::esl::fwd {p} { return [string map [list "\\" "/"] $p] }
proc ::esl::warn {msg} { variable warnings; lappend warnings $msg }
proc ::esl::short {s {n 300}} {
    if {[string length $s] > $n} { return "[string range $s 0 [expr {$n - 1}]]..." }
    return $s
}

# Mark the step about to run (failed_step in the json is the last marked step).
proc ::esl::step {name} { variable cur_step; set cur_step $name }

# Formatted HyperView error message (hwISession GetError), "" if none / not available.
proc ::esl::hverr {} {
    variable sess
    if {$sess eq ""} { return "" }
    set m ""
    catch {set m [$sess GetError]}
    return [string trim $m]
}

# Run one HyperView call as a named step; records ok/error in api, rethrows errors unchanged.
proc ::esl::do {name script} {
    variable cur_step
    variable steps_done
    variable api
    variable traces
    set cur_step $name
    if {[catch {uplevel 1 $script} res opts]} {
        set he [::esl::hverr]
        set msg "error: $res"
        if {$he ne ""} { append msg " | GetError: $he" }
        dict set api $name $msg
        dict set traces $name [dict get $opts -errorinfo]
        dict incr opts -level
        return -options $opts $res
    }
    lappend steps_done $name
    dict set api $name "ok: [::esl::short $res 120]"
    set cur_step "after $name"
    return $res
}

# Try alternatives {label script label script ...} in order; first success wins.
# api(name) = "ok: <label> -> <result>", failed alternatives in api(name.failed).
proc ::esl::alt {name cands} {
    variable cur_step
    variable steps_done
    variable api
    variable traces
    set cur_step $name
    set errs {}
    foreach {label script} $cands {
        if {[catch {uplevel 1 $script} res opts]} {
            set he [::esl::hverr]
            set m "$label: $res"
            if {$he ne ""} { append m " (GetError: $he)" }
            lappend errs $m
            dict set traces "$name/$label" [dict get $opts -errorinfo]
            continue
        }
        lappend steps_done "$name\[$label\]"
        dict set api $name "ok: $label -> [::esl::short $res 120]"
        if {[llength $errs] > 0} { dict set api "$name.failed" [join $errs " ; "] }
        set cur_step "after $name"
        return $res
    }
    dict set api $name "error: all failed: [join $errs { ; }]"
    return -code error -errorcode [list ESL_ALT $name] "$name failed (all alternatives): [join $errs { ; }]"
}

proc ::esl::parse_args {arglist} {
    array set a {input "" config "" output "" part ""}
    set n [llength $arglist]
    for {set i 0} {$i < $n} {incr i} {
        set k [string tolower [lindex $arglist $i]]
        if {$k in {-input -config -output -part}} {
            if {$i + 1 < $n} { incr i; set a([string range $k 1 end]) [lindex $arglist $i] }
        }
    }
    foreach {k ev} {input ESL_INPUT config ESL_CONFIG output ESL_OUTPUT part ESL_PART} {
        if {$a($k) eq "" && [info exists ::env($ev)]} { set a($k) $::env($ev) }
    }
    return [array get a]
}

# Environment facts for the json (all strings; never fails).
proc ::esl::collect_env {h3d} {
    variable env
    variable script_dir
    catch {dict set env tcl_version [info tclversion]}
    catch {dict set env tcl_patchLevel [info patchlevel]}
    catch {dict set env executable [::esl::fwd [info nameofexecutable]]}
    catch {dict set env argv $::argv}
    catch {dict set env os "$::tcl_platform(os) $::tcl_platform(osVersion) $::tcl_platform(machine)"}
    catch {dict set env pwd [::esl::fwd [pwd]]}
    catch {dict set env script_dir $script_dir}
    foreach ev {ALTAIR_HOME HW_ROOTDIR HW_UNITY_ROOTDIR HWVERSION ALTAIR_LICENSE_PATH} {
        if {[info exists ::env($ev)]} { dict set env "env_$ev" [::esl::fwd $::env($ev)] }
    }
    catch {dict set env hw_commands [lsort [concat [info commands hw*] [info commands ::hw*]]]}
    if {$h3d ne ""} {
        catch {dict set env input_ext [file extension $h3d]}
        catch {dict set env input_size [file size $h3d]}
        catch {dict set env input_mtime [clock format [file mtime $h3d] -format "%Y-%m-%d %H:%M:%S"]}
        catch {
            set fh [open $h3d rb]
            set head [read $fh 16]
            close $fh
            binary scan $head H* hx
            dict set env input_head_hex $hx
        }
    }
}

# HyperWorks version: try several (UNVERIFIED) API names, keep every answer that works.
proc ::esl::collect_hw_version {S} {
    variable env
    foreach {label script} [list \
        sess_GetSystemVersion [list $S GetSystemVersion] \
        sess_GetVersion [list $S GetVersion] \
        hwi_GetVersion {hwi GetVersion} \
        hwi_GetSystemVersion {hwi GetSystemVersion}] {
        if {![catch {uplevel #0 $script} v] && $v ne ""} { dict set env "hw_version.$label" $v }
    }
}

# Write a json file into dir; on failure fall back to the script folder (or ::ESL_FALLBACK_DIR)
# and always echo the body to stderr in that case. Returns the path written ("" if none).
proc ::esl::write_json {dir fname fbname body} {
    variable script_dir
    set fb $script_dir
    if {[info exists ::ESL_FALLBACK_DIR]} { set fb $::ESL_FALLBACK_DIR }
    set targets {}
    if {$dir ne ""} { lappend targets [list $dir $fname] }
    if {$fb ne ""} { lappend targets [list $fb $fbname] }
    set i 0
    foreach t $targets {
        lassign $t d f
        set p [file join $d $f]
        if {[catch {
            file mkdir $d
            set fh [open $p w]
            fconfigure $fh -translation lf -encoding utf-8
            puts $fh $body
            close $fh
        } e]} {
            puts stderr "ESL: cannot write $p: $e"
            incr i
            continue
        }
        if {$i > 0 || $dir eq ""} {
            puts stderr "ESL: wrote fallback $p"
            puts stderr $body
        }
        return $p
    }
    puts stderr $body
    return ""
}

# Diagnostic json members (without braces) for a failure.
proc ::esl::diag_members {err opts} {
    variable cur_step
    set ec ""
    set ei ""
    if {[dict exists $opts -errorcode]} { set ec [dict get $opts -errorcode] } elseif {[info exists ::errorCode]} { set ec $::errorCode }
    if {[dict exists $opts -errorinfo]} { set ei [dict get $opts -errorinfo] } elseif {[info exists ::errorInfo]} { set ei $::errorInfo }
    return "\"failed_step\":[::esl::jstr $cur_step],\"error\":[::esl::jstr $err],\"errorCode\":[::esl::jstr $ec],\"errorInfo\":[::esl::jstr $ei]"
}

# Members common to every json (steps, api, traces, env, components).
proc ::esl::trace_members {} {
    variable steps_done
    variable api
    variable traces
    variable env
    return "\"steps_done\":[::esl::jarr $steps_done],\"api\":[::esl::jobj $api],\"traces\":[::esl::jobj $traces],\"env\":[::esl::jobj $env],\"components\":[::esl::comps_json],\"components_source\":[::esl::jstr $::esl::comps_src]"
}

# Open the HyperView session, window client and model. Returns dict of handle names
# (S session, P project, PG page, W window, C client, M model, R result ctrl, Q query ctrl, mid).
# Every call is a named step; known failure points have alternatives.
proc ::esl::open_model {h3d} {
    variable sfx
    variable sess
    set x $sfx
    set S esl_sess_$x
    set P esl_proj_$x
    set C esl_post_$x
    set M esl_model_$x
    set R esl_res_$x
    set Q esl_qry_$x
    ::esl::step OpenStack
    if {[catch {::esl::do OpenStack {hwi OpenStack}} e]} { ::esl::warn "hwi OpenStack failed: $e" }
    ::esl::do GetSessionHandle {hwi GetSessionHandle $S}
    set sess $S
    ::esl::step hw_version
    ::esl::collect_hw_version $S
    ::esl::do GetProjectHandle {$S GetProjectHandle $P}
    set PG [::esl::alt GetPageHandle [list \
        active "set h esl_page_${x}_a; $P GetPageHandle \$h \[$P GetActivePage\]; set h" \
        index1 "set h esl_page_${x}_b; $P GetPageHandle \$h 1; set h"]]
    set W [::esl::alt GetWindowHandle [list \
        active "set h esl_win_${x}_a; $PG GetWindowHandle \$h \[$PG GetActiveWindow\]; set h" \
        index1 "set h esl_win_${x}_b; $PG GetWindowHandle \$h 1; set h" \
        index0 "set h esl_win_${x}_c; $PG GetWindowHandle \$h 0; set h" \
        project "set h esl_win_${x}_d; $P GetWindowHandle \$h; set h"]]
    set ct ""
    catch {set ct [::esl::do GetClientType {$W GetClientType}]}
    if {[string tolower $ct] ne "animation"} {
        ::esl::alt SetClientType [list \
            Animation [list $W SetClientType Animation] \
            animation [list $W SetClientType animation] \
            HyperView [list $W SetClientType HyperView] \
            hwc_client {hwc client animation} ]
    }
    ::esl::do GetClientHandle {$W GetClientHandle $C}
    catch {::esl::do GetModelReaderList {$C GetModelReaderList}}
    # AddModel returns the model id, 0 (Null_ID) on failure (poIPost AddModel docs)
    set q ""
    if {[string first " " $h3d] >= 0} { set q "\"" }
    set mid [::esl::alt AddModel [list \
        AddModel "::esl::model_id \[$C AddModel [list $h3d]\]" \
        AddModel_native "::esl::model_id \[$C AddModel [list [file nativename $h3d]]\]" \
        hwc_modelandresult "hwc open animation modelandresult $q$h3d$q $q$h3d$q; ::esl::active_model $C" \
        hwc_model "hwc open animation model $q$h3d$q; ::esl::active_model $C"]]
    ::esl::do GetModelHandle {$C GetModelHandle $M $mid}
    # AddModel reads the model only. Results must be attached with poIModel SetResult (and the
    # client drawn) before GetResultCtrlHandle, else HyperView raises 2051 "No results loaded"
    # (seen on HyperWorks 2026.1). A SetResult failure is kept (with GetError) in api/warnings
    # and added to the GetResultCtrlHandle error.
    set sr_err ""
    if {[catch {::esl::alt SetResult [list \
            SetResult [list $M SetResult $h3d] \
            SetResult_native [list $M SetResult [file nativename $h3d]]]} sr_err]} {
        ::esl::warn "SetResult failed: $sr_err"
    } else {
        set sr_err ""
    }
    if {[catch {::esl::do Draw {$C Draw}} e]} { ::esl::warn "Draw after SetResult failed: $e" }
    if {[catch {::esl::do GetResultCtrlHandle {$M GetResultCtrlHandle $R}} e opts]} {
        if {$sr_err ne ""} { append e " (results not loaded; SetResult failed: $sr_err)" }
        return -options $opts $e
    }
    ::esl::do GetQueryCtrlHandle {$M GetQueryCtrlHandle $Q}
    return [dict create S $S P $P PG $PG W $W C $C M $M R $R Q $Q mid $mid]
}

proc ::esl::model_id {r} {
    if {![string is integer -strict $r] || $r <= 0} { error "AddModel returned '$r' (0 = load failed)" }
    return $r
}
proc ::esl::active_model {C} {
    set r ""
    catch {set r [$C GetActiveModel]}
    if {![string is integer -strict $r] || $r <= 0} {
        catch {set r [lindex [$C GetModelList] end]}
    }
    return [::esl::model_id $r]
}

proc ::esl::norm_title {s} {
    return [string map [list " " "" "_" "" "\t" ""] [string tolower [string trim $s]]]
}

# Component (= Radioss part) list of the model: sets ::esl::comps to {{id name n_elems} ...}.
# Tries a query on a component selection set, then component/part handles (UNVERIFIED names).
proc ::esl::list_components {M Q {count 0}} {
    variable comps
    variable comps_src
    variable sfx
    ::esl::step components
    set csid [::esl::alt AddSelectionSet_component [list \
        component [list $M AddSelectionSet component] \
        part [list $M AddSelectionSet part]]]
    set CS esl_cset_$sfx
    ::esl::do GetSelectionSetHandle_component {$M GetSelectionSetHandle $CS $csid}
    ::esl::do ComponentSetAddAll {$CS Add all}
    set rows {}
    foreach fields {"component.id component.name" "part.id part.name" "component.id component.label"} {
        set got {}
        if {[catch {
            $Q SetSelectionSet $csid
            $Q SetQuery $fields
            set it esl_cit_$sfx
            $Q GetIteratorHandle $it
            for {$it First} {[$it Valid]} {$it Next} {
                set rec [$it GetDataList]
                lappend got [list [lindex $rec 0] [join [lrange $rec 1 end] " "]]
            }
            $it ReleaseHandle
        } e]} {
            catch {$it ReleaseHandle}
            dict set ::esl::api "component_query/$fields" "error: $e"
            continue
        }
        dict set ::esl::api "component_query/$fields" "rows [llength $got], first [::esl::short [lindex $got 0] 80]"
        set named 0
        foreach g $got {
            if {[lindex $g 1] ni {"" "N/A" "NA"}} { set named 1; break }
        }
        if {[llength $got] > 0 && [string is integer -strict [lindex $got 0 0]] && $named} {
            set rows $got
            set comps_src "query: $fields"
            dict set ::esl::api component_query "ok: $fields"
            break
        }
    }
    if {[llength $rows] == 0} {
        set ids {}
        catch {set ids [::esl::do ComponentSetGetList {$CS GetList}]}
        set H esl_comp_$sfx
        foreach id $ids {
            set name ""
            foreach getter {GetComponentHandle GetPartHandle} {
                if {[catch {$M $getter $H $id}]} { continue }
                foreach lab {GetLabel GetName} {
                    if {![catch {$H $lab} nm]} { set name $nm; break }
                }
                catch {$H ReleaseHandle}
                set comps_src "handles: $getter"
                break
            }
            lappend rows [list $id $name]
        }
        if {$comps_src eq ""} { set comps_src "ids only" }
    }
    catch {$CS ReleaseHandle}
    set out {}
    set ne -1
    set ES esl_ecnt_$sfx
    if {$count && [catch {$M GetSelectionSetHandle $ES [$M AddSelectionSet element]} e]} {
        ::esl::warn "component element counts unavailable: $e"
        set count 0
    }
    set k 0
    foreach r $rows {
        set ne -1
        if {$count && $k < 2000} {
            catch {
                $ES Clear
                $ES Add "component [lindex $r 0]"
                set ne [$ES GetSize]
            }
        }
        incr k
        lappend out [list [lindex $r 0] [lindex $r 1] $ne]
    }
    if {$count} { catch {$ES ReleaseHandle} }
    set comps $out
    lappend ::esl::steps_done components
    set ::esl::cur_step "after components"
    return $out
}

proc ::esl::comps_json {} {
    variable comps
    set rows {}
    foreach c $comps {
        lassign $c id name ne
        set idj [expr {[string is integer -strict $id] ? $id : [::esl::jstr $id]}]
        set r "\{\"id\":$idj,\"name\":[::esl::jstr $name]"
        if {$ne >= 0} { append r ",\"n_elems\":$ne" }
        lappend rows "$r\}"
    }
    return "\[[join $rows ,]\]"
}

# Part spec -> id. Integer = id; otherwise title compared ignoring case, blanks and underscores.
# Returns "" when spec is empty; errors (INPUT_INVALID) when no or several titles match.
proc ::esl::resolve_part {spec} {
    variable comps
    set spec [string trim $spec]
    if {$spec eq ""} { return "" }
    if {[string is integer -strict $spec]} { return $spec }
    set want [::esl::norm_title $spec]
    set hits {}
    foreach c $comps {
        if {[::esl::norm_title [lindex $c 1]] eq $want} { lappend hits [lindex $c 0] }
    }
    if {[llength $hits] == 1} { return [lindex $hits 0] }
    if {[llength $hits] > 1} {
        return -code error -errorcode {ESL INPUT_INVALID} "part title '$spec' matches several components: $hits"
    }
    return -code error -errorcode {ESL INPUT_INVALID} "part title '$spec' not found among [llength $comps] components (see components in the json; use -part <id>)"
}

# request.txt (optional): key<TAB>value, '#' comments. Missing file -> defaults (+ warning).
proc ::esl::read_request {path defaults} {
    set cfg $defaults
    if {$path eq ""} { return $cfg }
    if {![file isfile $path]} {
        ::esl::warn "request file not found, using defaults: $path"
        return $cfg
    }
    set fh [open $path r]
    fconfigure $fh -encoding utf-8
    set bad ""
    while {[gets $fh line] >= 0} {
        set line [string trimright $line "\r\n"]
        set t [string trim $line]
        if {$t eq "" || [string index $t 0] eq "#"} { continue }
        set tab [string first "\t" $line]
        if {$tab < 0} { set bad $line; break }
        dict set cfg [string trim [string range $line 0 [expr {$tab - 1}]]] \
            [string trim [string range $line [expr {$tab + 1}] end]]
    }
    close $fh
    if {$bad ne ""} { return -code error -errorcode {ESL INPUT_INVALID} "request.txt line without TAB: $bad" }
    return $cfg
}
# ---------------------------------------------------------------------------------------------
# end of common block
# ---------------------------------------------------------------------------------------------

namespace eval ::esl {
    variable warnings {}
    variable h3d ""
    variable numfmt "%.17g"
    variable backup_dir ""
    # result coordinate system for the strain tensor: requested name, applied call, warned flag
    variable sys_req "elemental"
    variable sys_applied ""
    variable sys_warned 0
}

# Number -> text with full double precision (never the raw query string).
proc ::esl::num {v} {
    variable numfmt
    return [format $numfmt $v]
}

# Move previous outputs to <out>/_backup/<timestamp>/ (file rename only, no delete).
proc ::esl::backup_outputs {out} {
    variable backup_dir
    set olds {}
    foreach f [glob -nocomplain -directory $out -types f -- done.json *.csv] {
        if {[lsearch -exact $olds $f] < 0} { lappend olds $f }
    }
    if {[llength $olds] == 0} { return "" }
    set stamp [clock format [clock seconds] -format "%Y%m%d_%H%M%S"]
    set dst [file join $out _backup $stamp]
    set k 1
    while {[file exists $dst]} {
        set dst [file join $out _backup "${stamp}_$k"]
        incr k
    }
    file mkdir $dst
    foreach f $olds {
        file rename -- $f [file join $dst [file tail $f]]
    }
    set backup_dir $dst
    ::esl::warn "previous outputs ([llength $olds] files) moved to [::esl::fwd $dst]"
    return $dst
}

# Ask HyperView to resolve contour (tensor) results in the requested system.
# The API name differs between versions (UNVERIFIED): try several, warn once if none works.
proc ::esl::set_system {con} {
    variable sys_req
    variable sys_applied
    variable sys_warned
    set req [string tolower $sys_req]
    if {$req eq "" || $req eq "none"} { return }
    switch -- $req {
        elemental { set names {"Elemental System" "Elemental" "elemental" "element"} }
        analysis  { set names {"Analysis System" "Analysis" "analysis"} }
        global    { set names {"Global System" "Global" "global"} }
        default   { ::esl::fail INPUT_INVALID "strain_system must be elemental|analysis|global|none: $sys_req" }
    }
    set calls {}
    foreach n $names { lappend calls [list SetResolvedIn $n] }
    foreach n $names { lappend calls [list SetResultSystem $n] }
    foreach n $names { lappend calls [list SetSystemType $n] }
    foreach n $names { lappend calls [list SetSystem $n] }
    if {$sys_applied ne ""} {
        # reuse the call that worked before (SetDataType may reset the system)
        set calls [linsert $calls 0 $sys_applied]
    }
    foreach c $calls {
        if {![catch {$con {*}$c}]} {
            set sys_applied $c
            return
        }
    }
    if {!$sys_warned} {
        set sys_warned 1
        ::esl::warn "could not set result system '$sys_req' (tried SetResolvedIn/SetResultSystem/SetSystemType/SetSystem); strain is in the HyperView default system - verify it is the element system"
    }
}

proc ::esl::fail {code msg} {
    return -code error -errorcode [list ESL $code] $msg
}

proc ::esl::read_config {path} {
    set defaults [dict create part_id "" part_title "" subcase 1 frame_stride 1 strain_type "Strain" \
        strain_comps "XX YY XY" layer_bottom "Lower" layer_top "Upper" layer_mid "" \
        shear_is_engineering 0 disp_type "Displacement" disp_comps "X Y Z" \
        elem_selection "" node_selection "" strain_system "elemental"]
    set cfg [::esl::read_request $path $defaults]
    set p [dict get $cfg part_id]
    if {$p ne "" && ![string is integer -strict $p]} {
        ::esl::fail INPUT_INVALID "part_id must be an integer (use part_title or -part for names): $p"
    }
    set fs [dict get $cfg frame_stride]
    if {![string is integer -strict $fs] || $fs < 1} { ::esl::fail INPUT_INVALID "frame_stride must be >= 1" }
    if {[llength [dict get $cfg strain_comps]] != 3} { ::esl::fail INPUT_INVALID "strain_comps needs 3 names" }
    if {[llength [dict get $cfg disp_comps]] != 3} { ::esl::fail INPUT_INVALID "disp_comps needs 3 names" }
    return $cfg
}


# Time value from a simulation label such as "Time = 1.000000E-03" (number after '=' or last number).
proc ::esl::label_time {label} {
    set re {[-+]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eEdD][-+]?[0-9]+)?}
    set eq [string last "=" $label]
    if {$eq >= 0} {
        if {[regexp -- $re [string range $label [expr {$eq + 1}] end] num]} {
            return [string map {d e D e} $num]
        }
    }
    set nums [regexp -all -inline -- $re $label]
    if {[llength $nums] > 0} { return [string map {d e D e} [lindex $nums end]] }
    return ""
}

# Fill a selection set with the target part; tries several selection-string spellings.
proc ::esl::select_part {sethandle pid custom} {
    set tries {}
    if {$custom ne ""} { lappend tries $custom }
    lappend tries "component $pid" "comp $pid" "part $pid"
    foreach s $tries {
        catch {$sethandle Clear}
        if {[catch {$sethandle Add $s}]} { continue }
        set n 0
        catch {set n [$sethandle GetSize]}
        if {$n > 0} { return [list $s $n] }
    }
    catch {$sethandle Clear}
    $sethandle Add "all"
    set n 0
    catch {set n [$sethandle GetSize]}
    ::esl::warn "part selection failed for part $pid; using 'all' ($n entities, other parts filtered in Python)"
    return [list "all" $n]
}

proc ::esl::set_contour {con dtype comp layer {tensor 0}} {
    $con SetDataType $dtype
    if {$tensor} { ::esl::set_system $con }
    $con SetDataComponent $comp
    if {$layer ne ""} { $con SetLayer $layer }
    catch {$con SetAverageMode none}
    catch {$con SetEnableState true}
}

# Run a query; returns flat records {id v1 v2 ...} (nested lists flattened).
proc ::esl::query {qry setid fields} {
    $qry SetSelectionSet $setid
    $qry SetQuery $fields
    set it esl_it_$::esl::sfx
    $qry GetIteratorHandle $it
    set out {}
    if {[catch {
        for {$it First} {[$it Valid]} {$it Next} {
            set rec {}
            foreach v [$it GetDataList] { foreach w $v { lappend rec $w } }
            lappend out $rec
        }
    } err]} {
        catch {$it ReleaseHandle}
        error $err
    }
    $it ReleaseHandle
    return $out
}

# id -> value dict for current contour; non-numeric values are dropped (counted as warning).
proc ::esl::contour_values {qry setid entity what} {
    set d [dict create]
    set bad 0
    foreach rec [::esl::query $qry $setid "$entity.id contour.value"] {
        set id [lindex $rec 0]
        set v [lindex $rec 1]
        if {[string is integer -strict $id] && [string is double -strict $v]} {
            dict set d $id $v
        } else {
            incr bad
        }
    }
    if {$bad > 0} { ::esl::warn "$what: $bad non-numeric values skipped" }
    return $d
}

proc ::esl::open_csv {path header} {
    set fh [open $path w]
    fconfigure $fh -translation lf -encoding ascii -buffering full
    puts $fh $header
    return $fh
}

proc ::esl::write_done {out ok extra {raw ""}} {
    variable warnings
    variable h3d
    set body "\"ok\":[expr {$ok ? "true" : "false"}],\"h3d\":[::esl::jstr $h3d]"
    foreach {k v} $extra { append body ",[::esl::jstr $k]:$v" }
    if {$raw ne ""} { append body ",$raw" }
    append body ",[::esl::trace_members],\"warnings\":[::esl::jarr $warnings]"
    return [::esl::write_json $out done.json esl_extract_done_fallback.json "\{$body\}"]
}

proc ::esl::run {arglist} {
    variable h3d
    ::esl::step args
    array set a [::esl::parse_args $arglist]
    if {$a(input) ne ""} { set h3d [::esl::fwd $a(input)] }
    ::esl::collect_env $h3d
    if {$a(output) eq ""} { ::esl::fail INPUT_INVALID "missing -output <dir>" }
    set out [::esl::fwd $a(output)]
    set ::esl::outdir $out
    ::esl::step mkdir_output
    file mkdir $out
    ::esl::step backup_outputs
    ::esl::backup_outputs $out
    ::esl::step check_input
    if {$a(input) eq ""} { ::esl::fail INPUT_INVALID "missing -input <h3d>" }
    if {![file isfile $h3d]} { ::esl::fail TOOL_OUTPUT_MISSING "h3d not found: $h3d" }
    ::esl::step read_request
    set cfg [::esl::read_config [::esl::fwd $a(config)]]
    set spec [string trim $a(part)]
    if {$spec eq ""} { set spec [dict get $cfg part_id] }
    if {$spec eq ""} { set spec [dict get $cfg part_title] }
    set ::esl::part_spec $spec
    set sc [dict get $cfg subcase]
    set stride [dict get $cfg frame_stride]
    set stype [dict get $cfg strain_type]
    set dtype [dict get $cfg disp_type]
    set eng [expr {[dict get $cfg shear_is_engineering] eq "1"}]
    set ::esl::sys_req [dict get $cfg strain_system]
    if {[lsearch -exact {elemental analysis global none} [string tolower $::esl::sys_req]] < 0} {
        ::esl::fail INPUT_INVALID "strain_system must be elemental|analysis|global|none: $::esl::sys_req"
    }
    set layers [list bottom [dict get $cfg layer_bottom] top [dict get $cfg layer_top]]
    if {[dict get $cfg layer_mid] ne ""} { lappend layers mid [dict get $cfg layer_mid] }

    # ---- session / model (every call is a named step; see done.json failed_step / api)
    set hd [::esl::open_model $h3d]
    set post [dict get $hd C]
    set model [dict get $hd M]
    set res [dict get $hd R]
    set qry [dict get $hd Q]
    set x $::esl::sfx

    # ---- part: id, or title looked up in the component list
    set need_list [expr {$spec eq "" || ![string is integer -strict $spec]}]
    if {[catch {::esl::list_components $model $qry 0} e]} {
        if {$need_list} { error "component list failed at $::esl::cur_step: $e" }
        ::esl::warn "component list failed: $e"
    }
    ::esl::step resolve_part
    if {$spec eq ""} {
        ::esl::fail INPUT_INVALID "no part given: pass -part <title or id> (e.g. -part chassis_rear); see components in done.json"
    }
    set pid [::esl::resolve_part $spec]
    set ::esl::part_id $pid
    set ptitle ""
    foreach c $::esl::comps {
        if {[lindex $c 0] eq $pid} { set ptitle [lindex $c 1] }
    }

    ::esl::step GetSubcaseList
    set subcases {}
    catch {set subcases [::esl::do GetSubcaseList {$res GetSubcaseList}]}
    if {[llength $subcases] == 0} {
        catch {::esl::do SetResult_retry {$model SetResult $h3d}}
        catch {set subcases [::esl::do GetSubcaseList_retry {$res GetSubcaseList}]}
    }
    if {[lsearch -exact $subcases $sc] < 0} {
        ::esl::fail H3D_MISSING_RESULT "subcase $sc not in h3d (available: $subcases)"
    }
    ::esl::do SetCurrentSubcase {$res SetCurrentSubcase $sc}
    set sims [::esl::do GetSimulationList {$res GetSimulationList $sc}]
    set nsim [llength $sims]
    if {$nsim == 0} { ::esl::fail H3D_MISSING_RESULT "subcase $sc has no simulations" }
    set dtypes [::esl::do GetDataTypeList {$res GetDataTypeList $sc}]
    foreach t [list $stype $dtype] {
        if {[lsearch -exact $dtypes $t] < 0} {
            ::esl::fail H3D_MISSING_RESULT "result type '$t' not in subcase $sc (available: $dtypes)"
        }
    }
    set con esl_con_$x
    ::esl::do GetContourCtrlHandle {$res GetContourCtrlHandle $con}

    # ---- selections
    set eset esl_eset_$x
    set nset esl_nset_$x
    set eset_id [::esl::do AddSelectionSet_element {$model AddSelectionSet element}]
    ::esl::do GetSelectionSetHandle_element {$model GetSelectionSetHandle $eset $eset_id}
    ::esl::step select_part_element
    set esel [::esl::select_part $eset $pid [dict get $cfg elem_selection]]
    set nset_id [::esl::do AddSelectionSet_node {$model AddSelectionSet node}]
    ::esl::do GetSelectionSetHandle_node {$model GetSelectionSetHandle $nset $nset_id}
    ::esl::step select_part_node
    set nsel [::esl::select_part $nset $pid [dict get $cfg node_selection]]
    ::esl::step write_csv

    set ffr [::esl::open_csv [file join $out frames.csv] "frame_index,time"]
    set fst [::esl::open_csv [file join $out strain.csv] "frame_index,elem_id,layer,exx,eyy,exy"]
    set fds [::esl::open_csv [file join $out disp.csv] "frame_index,node_id,ux,uy,uz"]
    set nframes 0
    set nelem 0
    set nnode 0
    set scomps [dict get $cfg strain_comps]
    set dcomps [dict get $cfg disp_comps]
    for {set fi 0} {$fi < $nsim} {incr fi $stride} {
        ::esl::step "frame $fi SetCurrentSimulation"
        $res SetCurrentSimulation $fi
        catch {$post Draw}
        set t [::esl::label_time [lindex $sims $fi]]
        if {$t eq ""} {
            set t $fi
            ::esl::warn "frame $fi: no time in label '[lindex $sims $fi]'; time = frame index"
        }
        if {![string is double -strict $t]} { set t $fi }
        puts $ffr "$fi,[::esl::num $t]"

        if {$nframes == 0} {
            # initial coordinates (first written frame; frame 0 is expected to be undeformed)
            set fmo [::esl::open_csv [file join $out model.csv] "node_id,x0,y0,z0"]
            foreach rec [::esl::query $qry $nset_id "node.id node.coords"] {
                if {[llength $rec] >= 4 && [string is double -strict [lindex $rec 1]] \
                        && [string is double -strict [lindex $rec 2]] && [string is double -strict [lindex $rec 3]]} {
                    puts $fmo "[lindex $rec 0],[::esl::num [lindex $rec 1]],[::esl::num [lindex $rec 2]],[::esl::num [lindex $rec 3]]"
                }
            }
            close $fmo
            if {$fi != 0} { ::esl::warn "model.csv written at frame $fi (not 0)" }
        }

        # strain tensor per layer
        foreach {lname hvlayer} $layers {
            set vals {}
            foreach c $scomps {
                ::esl::step "frame $fi strain $c $hvlayer"
                ::esl::set_contour $con $stype $c $hvlayer 1
                lappend vals [::esl::contour_values $qry $eset_id element "strain $c $hvlayer frame $fi"]
            }
            lassign $vals dxx dyy dxy
            set cnt 0
            dict for {eid exx} $dxx {
                if {![dict exists $dyy $eid] || ![dict exists $dxy $eid]} { continue }
                set exy [dict get $dxy $eid]
                if {$eng} { set exy [expr {0.5 * $exy}] }
                puts $fst "$fi,$eid,$lname,[::esl::num $exx],[::esl::num [dict get $dyy $eid]],[::esl::num $exy]"
                incr cnt
            }
            if {$cnt == 0} {
                ::esl::fail H3D_MISSING_RESULT "no strain values for layer '$hvlayer' at frame $fi"
            }
            if {$cnt > $nelem} { set nelem $cnt }
        }

        # displacement (global)
        set vals {}
        foreach c $dcomps {
            ::esl::step "frame $fi disp $c"
            ::esl::set_contour $con $dtype $c ""
            lappend vals [::esl::contour_values $qry $nset_id node "disp $c frame $fi"]
        }
        lassign $vals dx dy dz
        set cnt 0
        dict for {nid ux} $dx {
            if {![dict exists $dy $nid] || ![dict exists $dz $nid]} { continue }
            puts $fds "$fi,$nid,[::esl::num $ux],[::esl::num [dict get $dy $nid]],[::esl::num [dict get $dz $nid]]"
            incr cnt
        }
        if {$cnt == 0} { ::esl::fail H3D_MISSING_RESULT "no displacement values at frame $fi" }
        if {$cnt > $nnode} { set nnode $cnt }
        incr nframes
    }
    close $ffr
    close $fst
    close $fds
    ::esl::step CloseStack
    catch {hwi CloseStack}
    ::esl::step write_done
    set ::esl::cur_step "done"
    lappend ::esl::steps_done write_csv
    if {[::esl::write_done $out 1 [list part_id $pid part_title [::esl::jstr $ptitle] \
        part_spec [::esl::jstr $spec] n_frames $nframes n_elems $nelem n_nodes $nnode \
        subcase [::esl::jstr $sc] elem_selection [::esl::jstr [lindex $esel 0]] \
        node_selection [::esl::jstr [lindex $nsel 0]] \
        disp_value_format [::esl::jstr $::esl::numfmt] value_format [::esl::jstr $::esl::numfmt] \
        strain_system [::esl::jstr $::esl::sys_req] \
        strain_system_call [::esl::jstr $::esl::sys_applied] \
        backup_dir [::esl::jstr [::esl::fwd $::esl::backup_dir]]]] eq ""} {
        error "done.json could not be written"
    }
    set ::esl::written 1
}

set ::esl::part_spec ""
set ::esl::part_id ""
set ::esl::written 0
set ::esl::rc 0
if {[catch {::esl::run $::argv} ::esl::err ::esl::opts]} {
    set ::esl::code TOOL_LOG_ERROR
    set ::esl::ec [dict get $::esl::opts -errorcode]
    if {[lindex $::esl::ec 0] eq "ESL"} { set ::esl::code [lindex $::esl::ec 1] }
    catch {hwi CloseStack}
    if {!$::esl::written} {
        set ::esl::pidj [expr {[string is integer -strict $::esl::part_id] ? $::esl::part_id : "null"}]
        if {[catch {::esl::write_done $::esl::outdir 0 [list code [::esl::jstr $::esl::code] \
                part_spec [::esl::jstr $::esl::part_spec] part_id $::esl::pidj] \
                [::esl::diag_members $::esl::err $::esl::opts]} ::esl::werr]} {
            puts stderr "ESL: done.json not written: $::esl::werr"
        }
    }
    puts stderr "ESL extract failed at step '$::esl::cur_step': $::esl::code: $::esl::err"
    set ::esl::rc 1
}
if {![info exists ::ESL_NO_EXIT]} { exit $::esl::rc }
