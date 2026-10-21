# esl_h3d_extract.tcl -- HyperView batch extractor for the ESL core (contract: esl_core.md 7.2)
#
#   hw -clientconfig hwpost.dat -b -tcl esl_h3d_extract.tcl -input <h3d> -part <title|id> -output <dir>
#      [-config <request.txt>] [-hot_k <n>] [-top_n <n>]
#
# Results in the h3d are per-element MAX-HOLD values (Max_Strain tensor, Plastic Strain, layer Mid):
# a value stays at its maximum once reached, so t* is the frame where the final value is FIRST
# reached (first-reach). One run, three passes:
#   (A) last frame, all part elements          -> final.csv
#   (B) every frame, hot set H only            -> history.csv
#       H = top hot_k by final vonMises U top hot_k by final plastic strain (values > 0, no size cap)
#   (C) candidate frames D, all part elements and nodes -> strain_frames.csv, disp.csv
#       + previous frames P = { f-1 >= 0 : f in D } (not already in D), all part elements only
#       -> strain_frames.csv (same format, told apart by frame_index; for the all-element
#       "rising" mask v[f] > v[f-1]*(1+rtol), contract esl_p2_library.md 7.1)
#       D = for each metric (vonMises, plastic strain): walk H by final value (descending, ties: lower id)
#       and collect distinct first-reach frames, up to top_n per metric.
#   first_reach(e) = min{ f : v[f,e] >= v[last,e]*(1-reach_rtol) }
#
# Writes into <dir>:
#   frames.csv         frame_index,time                                 (all frames)
#   model.csv          node_id,x0,y0,z0                                 (part nodes, frame 0)
#   final.csv          elem_id,vm_hv,exx,eyy,ezz,exy,epsp               (A)
#   history.csv        frame_index,elem_id,vm_hv,exx,eyy,ezz,exy,epsp   (B)
#   strain_frames.csv  frame_index,elem_id,vm_hv,exx,eyy,ezz,exy,epsp   (C: frames D and P)
#   disp.csv           frame_index,node_id,ux,uy,uz                     (C)
#   done.json          {"ok":true,"candidate_frames":{"max_strain":[..],"plastic_strain":[..]},"frames_D",
#                       "prev_frames" (f-1 >= 0 of each f in D),"strain_frames" (D U prev),
#                       "hot_k","reach_rtol","passes":{...},...} or {"ok":false,"code","error","failed_step",
#                       "errorCode","errorInfo","steps_done","api","traces","env","components",...}
#                      (ALWAYS written; if <dir> cannot be written: stderr + esl_extract_done_fallback.json)
# exy is written as stored in the h3d (tensor or engineering shear is decided in Python).
# Large parts: element/node queries run per chunk (request key "chunk", default 50000 ids, one
# selection set per chunk built once by id ranges) and rows go straight to the files. Progress
# (pass / frame / chunk) is printed on the console; per-pass rows and seconds go to done.json.
#
# Part: -part <id or title> > request.txt part_id > request.txt part_title. A title is matched
# against the h3d component names ignoring case, blanks and underscores ("Chassis Rear" ==
# "chassis_rear"). Without a part: done.json ok:false (INPUT_INVALID) with the component list.
#
# request.txt (OPTIONAL; missing -> defaults): one "key<TAB>value" per line, '#' lines ignored. Keys:
#   part_id, part_title, subcase (1), strain_type (Max_Strain), strain_comps (XX YY ZZ XY),
#   vm_comp (vonMises), strain_layer (Mid), epsp_type (Plastic Strain; empty = no plastic strain, 0),
#   epsp_comp (Scalar value), epsp_layer (Mid), disp_type (Displacement), disp_comps (X Y Z),
#   hot_k (200, no upper cap; > 1000 warns), top_n (5), reach_rtol (1e-6), chunk (50000),
#   elem_selection / node_selection (optional HyperView selection string, e.g. "component 12"),
#   strain_system (elemental | analysis | global | none; default elemental).
#   -hot_k / -top_n arguments override request.txt.
#
# Progress: every ::esl::progress / coarse step start / long call (model load, result load) is
# also appended, with a timestamp and flushed per line, to <dir>/progress.log (hw.exe in -b mode
# may not forward Tcl stdout to the worker log; the worker tails progress.log instead).
#
# Existing outputs (done.json, progress.log, *.csv) in <dir> are moved to <dir>/_backup/<timestamp>/ first
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
    # progress.log (append, flushed per line); enabled only after the previous one was backed up
    variable plog_on 0
    variable plog_fh ""
    variable plog_t [dict create]
    # result coordinate system for the strain tensor: requested name, applied call, warned flag
    variable sys_req "elemental"
    variable sys_applied ""
    variable sys_warned 0
    # aggregated notes (message -> count) and per-pass statistics (json members)
    variable notes [dict create]
    variable passes {}
    variable chunk_how [dict create]
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
    foreach f [glob -nocomplain -directory $out -types f -- done.json progress.log *.csv] {
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

# Append one timestamped line to <out>/progress.log and flush (never raises).
proc ::esl::plog {msg} {
    variable plog_on
    variable plog_fh
    variable outdir
    if {!$plog_on} { return }
    catch {
        if {$plog_fh eq ""} {
            set plog_fh [open [file join $outdir progress.log] a]
            fconfigure $plog_fh -translation lf -encoding ascii -buffering line
        }
        puts $plog_fh "[clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}] $msg"
        flush $plog_fh
    }
}

proc ::esl::plog_close {} {
    variable plog_fh
    catch {close $plog_fh}
    set plog_fh ""
}

proc ::esl::progress {msg} {
    catch {
        puts stdout "ESL extract [clock format [clock seconds] -format %H:%M:%S] $msg"
        flush stdout
    }
    ::esl::plog $msg
}

# Coarse steps are logged when they start; per-frame / per-chunk / per-field steps are not
# (those are covered by ::esl::progress). Redefines the common-block proc (same behaviour + log).
proc ::esl::step {name} {
    variable cur_step
    set cur_step $name
    if {![string match "frame *" $name] && [string first chunk $name] < 0 && [string first / $name] < 0} {
        ::esl::plog "step $name"
    }
}

# Long HyperView calls (model load, result load, draw): "<label> start" / "<label> end <sec>s".
# Execution traces on ::esl::alt / ::esl::do (Tcl 8.5).
proc ::esl::plog_trace {cmd args} {
    variable plog_t
    catch {
        set labels [dict create AddModel "model load" SetResult "result load" Draw "draw" \
            GetResultCtrlHandle "result ctrl handle"]
        set op [lindex $args end]
        set name [lindex $cmd 1]
        if {![dict exists $labels $name]} { return }
        set label [dict get $labels $name]
        if {$op eq "enter"} {
            dict set plog_t $name [clock milliseconds]
            ::esl::plog "$label start"
        } else {
            set sec "?"
            if {[dict exists $plog_t $name]} {
                set sec [format %.1f [expr {([clock milliseconds] - [dict get $plog_t $name]) / 1000.0}]]
            }
            set bad ""
            if {[lindex $args 0] != 0} { set bad " (error)" }
            ::esl::plog "$label done (${sec} s)$bad"
        }
    }
}
trace add execution ::esl::alt enter ::esl::plog_trace
trace add execution ::esl::alt leave ::esl::plog_trace
trace add execution ::esl::do enter ::esl::plog_trace
trace add execution ::esl::do leave ::esl::plog_trace

# Repeated per-frame/per-chunk messages are counted, not repeated (added to warnings at the end).
proc ::esl::note {msg {n 1}} {
    variable notes
    dict incr notes $msg $n
}

proc ::esl::flush_notes {} {
    variable notes
    dict for {m n} $notes { ::esl::warn "$m (x$n)" }
    set notes [dict create]
}

proc ::esl::ms {} { return [clock milliseconds] }
proc ::esl::secs {t0} { return [format %.3f [expr {([clock milliseconds] - $t0) / 1000.0}]] }

# extract-only arguments: -hot_k <n>, -top_n <n> (env ESL_HOT_K / ESL_TOP_N)
proc ::esl::extra_args {arglist} {
    set out [dict create]
    set n [llength $arglist]
    for {set i 0} {$i < $n} {incr i} {
        set k [string tolower [lindex $arglist $i]]
        if {($k eq "-hot_k" || $k eq "-top_n") && $i + 1 < $n} {
            incr i
            dict set out [string range $k 1 end] [lindex $arglist $i]
        }
    }
    foreach {k ev} {hot_k ESL_HOT_K top_n ESL_TOP_N} {
        if {![dict exists $out $k] && [info exists ::env($ev)]} { dict set out $k $::env($ev) }
    }
    return $out
}

proc ::esl::read_config {path extra} {
    set defaults [dict create part_id "" part_title "" subcase 1 \
        strain_type "Max_Strain" strain_comps "XX YY ZZ XY" vm_comp "vonMises" strain_layer "Mid" \
        epsp_type "Plastic Strain" epsp_comp "Scalar value" epsp_layer "Mid" \
        disp_type "Displacement" disp_comps "X Y Z" \
        hot_k 200 top_n 5 reach_rtol 1e-6 chunk 50000 \
        elem_selection "" node_selection "" strain_system "elemental"]
    set cfg [::esl::read_request $path $defaults]
    dict for {k v} $extra { dict set cfg $k $v }
    set p [dict get $cfg part_id]
    if {$p ne "" && ![string is integer -strict $p]} {
        ::esl::fail INPUT_INVALID "part_id must be an integer (use part_title or -part for names): $p"
    }
    foreach k {hot_k top_n chunk} {
        set v [dict get $cfg $k]
        if {![string is integer -strict $v] || $v < 1} { ::esl::fail INPUT_INVALID "$k must be an integer >= 1: $v" }
    }
    set r [dict get $cfg reach_rtol]
    if {![string is double -strict $r] || $r < 0 || $r >= 1} { ::esl::fail INPUT_INVALID "reach_rtol must be in \[0, 1): $r" }
    if {[llength [dict get $cfg strain_comps]] != 4} { ::esl::fail INPUT_INVALID "strain_comps needs 4 names (xx yy zz xy)" }
    if {[llength [dict get $cfg disp_comps]] != 3} { ::esl::fail INPUT_INVALID "disp_comps needs 3 names" }
    return $cfg
}

# Contour fields of an element row: vm_hv exx eyy ezz exy [epsp]; each {type component layer tensor}.
proc ::esl::elem_fields {cfg} {
    set st [dict get $cfg strain_type]
    set sl [dict get $cfg strain_layer]
    lassign [dict get $cfg strain_comps] cxx cyy czz cxy
    set f [list [list $st [dict get $cfg vm_comp] $sl 0] [list $st $cxx $sl 1] [list $st $cyy $sl 1] \
        [list $st $czz $sl 1] [list $st $cxy $sl 1]]
    if {[dict get $cfg epsp_type] ne ""} {
        lappend f [list [dict get $cfg epsp_type] [dict get $cfg epsp_comp] [dict get $cfg epsp_layer] 0]
    }
    return $f
}

# Result type / component / layer present in the subcase (component and layer lists only if the API answers).
proc ::esl::check_result {res sc dtypes dt comps layer} {
    if {[lsearch -exact $dtypes $dt] < 0} {
        ::esl::fail H3D_MISSING_RESULT "result type '$dt' not in subcase $sc (available: $dtypes)"
    }
    if {![catch {$res GetDataComponentList $sc $dt} have] && [llength $have] > 0} {
        foreach c $comps {
            if {[lsearch -exact $have $c] < 0} {
                ::esl::fail H3D_MISSING_RESULT "component '$c' of '$dt' not in h3d (available: $have)"
            }
        }
    }
    if {$layer ne "" && ![catch {$res GetLayerList $sc $dt} ls] && [llength $ls] > 0 && [lsearch -exact $ls $layer] < 0} {
        ::esl::fail H3D_MISSING_RESULT "layer '$layer' of '$dt' not in h3d (available: $ls)"
    }
}

# Stream one query over a selection set; body runs per record with rec = flat {id v1 v2 ...}.
proc ::esl::each_rec {qry setid fields recvar body} {
    upvar 1 $recvar rec
    $qry SetSelectionSet $setid
    $qry SetQuery $fields
    set it esl_it_$::esl::sfx
    $qry GetIteratorHandle $it
    if {[catch {
        for {$it First} {[$it Valid]} {$it Next} {
            set rec [concat {*}[$it GetDataList]]
            uplevel 1 $body
        }
    } err opts]} {
        catch {$it ReleaseHandle}
        return -options $opts $err
    }
    $it ReleaseHandle
}

# Contour values of several fields on one selection set: dict id -> {v1 v2 ...} (only ids that got
# every field in order). keep: optional dict of wanted ids. what: label for steps/notes.
proc ::esl::collect {con qry setid entity fields what {keep ""}} {
    set acc [dict create]
    set k 0
    foreach f $fields {
        lassign $f dt comp layer tensor
        ::esl::step "$what $dt/$comp/$layer"
        ::esl::set_contour $con $dt $comp $layer $tensor
        set bad 0
        set good 0
        ::esl::each_rec $qry $setid "$entity.id contour.value" rec {
            set id [lindex $rec 0]
            set v [lindex $rec 1]
            if {![string is integer -strict $id] || ![string is double -strict $v]} {
                incr bad
            } elseif {$keep eq "" || [dict exists $keep $id]} {
                if {$k == 0} {
                    if {![dict exists $acc $id]} { dict set acc $id [list $v]; incr good }
                } elseif {[dict exists $acc $id] && [llength [dict get $acc $id]] == $k} {
                    dict lappend acc $id $v
                    incr good
                }
            }
        }
        if {$bad > 0} { ::esl::note "[lindex $what 0] [lindex $what 1] $dt/$comp/$layer: non-numeric values skipped" $bad }
        if {$good == 0 && $keep eq ""} {
            ::esl::fail H3D_MISSING_RESULT "no values for $dt/$comp/$layer ($what)"
        }
        incr k
    }
    return $acc
}

# Write rows "<prefix><id>,v1,...[,0 x pad]" for complete records. Optional top collection for pass A.
proc ::esl::emit {fh prefix acc nreal pad {topvar ""}} {
    if {$topvar ne ""} { upvar 1 $topvar top }
    set n 0
    set miss 0
    set zeros [string repeat ",0" $pad]
    dict for {id vs} $acc {
        if {[llength $vs] != $nreal} { incr miss; continue }
        set o {}
        foreach v $vs { lappend o [format $::esl::numfmt $v] }
        puts $fh "$prefix$id,[join $o ,]$zeros"
        incr n
        if {$topvar ne ""} {
            set v0 [lindex $vs 0]
            if {$v0 > 0} { dict lappend top vm [list $id $v0] }
            if {$nreal >= 6} {
                set v5 [lindex $vs 5]
                if {$v5 > 0} { dict lappend top ep [list $id $v5] }
            }
        }
    }
    return [list $n $miss]
}

# Top k {id value} pairs: value descending, ties lower id first (stable lsort).
proc ::esl::topk {pairs k} {
    set pairs [lsort -integer -index 0 $pairs]
    set pairs [lsort -real -decreasing -index 1 $pairs]
    return [lrange $pairs 0 [expr {$k - 1}]]
}

proc ::esl::first_reach {vals rtol} {
    set thr [expr {[lindex $vals end] * (1.0 - $rtol)}]
    set i 0
    foreach v $vals {
        if {$v >= $thr} { return $i }
        incr i
    }
    return [expr {[llength $vals] - 1}]
}

# D rule for one metric: hist = dict id -> per-frame values. Returns {frames elems}.
proc ::esl::cand_frames {hist ids rtol top_n} {
    set pairs {}
    foreach id $ids {
        set v [lindex [dict get $hist $id] end]
        if {$v > 0} { lappend pairs [list $id $v] }
    }
    set pairs [::esl::topk $pairs [llength $pairs]]
    set fr {}
    set el {}
    foreach p $pairs {
        if {[llength $fr] >= $top_n} { break }
        set f [::esl::first_reach [dict get $hist [lindex $p 0]] $rtol]
        if {[lsearch -exact $fr $f] < 0} {
            lappend fr $f
            lappend el [lindex $p 0]
        }
    }
    return [list $fr $el]
}

# Sorted integer ids -> compact ranges {a-b c ...}
proc ::esl::ranges {ids} {
    set out {}
    set s ""
    set p ""
    foreach i $ids {
        if {$s eq ""} { set s $i; set p $i; continue }
        if {$i == $p + 1} { set p $i; continue }
        if {$s == $p} { lappend out $s } else { lappend out "$s-$p" }
        set s $i
        set p $i
    }
    if {$s ne ""} {
        if {$s == $p} { lappend out $s } else { lappend out "$s-$p" }
    }
    return $out
}

# Number of entities in a set: GetSize, else a counting query.
proc ::esl::set_count {S qry setid entity} {
    set got -1
    catch {set got [$S GetSize]}
    if {$got < 0} {
        set got 0
        if {[catch {::esl::each_rec $qry $setid "$entity.id" rec { incr got }}]} { set got -1 }
    }
    return $got
}

# All ids of a selection set (sorted, unique): GetList, else a streaming id query.
proc ::esl::set_ids {S qry setid entity} {
    if {![catch {$S GetList} l] && [llength $l] > 0} {
        set ok 1
        foreach i $l { if {![string is integer -strict $i]} { set ok 0; break } }
        if {$ok} { return [lsort -integer -unique $l] }
    }
    set ids {}
    ::esl::each_rec $qry $setid "$entity.id" rec { lappend ids [lindex $rec 0] }
    return [lsort -integer -unique $ids]
}

# Fill set S with exactly the given ids (UNVERIFIED selection syntax): one call with an id-range
# string ("id a-b c", "<entity> a-b c", comma form), else one Add per id. Verified by the set size.
# Returns the method used, "" if none worked.
proc ::esl::select_ids {S qry setid entity ids} {
    set n [llength $ids]
    set rg [::esl::ranges $ids]
    foreach s [list "id [join $rg { }]" "$entity [join $rg { }]" "id [join $rg ,]" "$entity [join $rg ,]"] {
        catch {$S Clear}
        if {[catch {$S Add $s}]} { continue }
        if {[::esl::set_count $S $qry $setid $entity] == $n} { return "range: [lindex $s 0]" }
    }
    foreach pre [list id $entity] {
        catch {$S Clear}
        set ok 1
        foreach i $ids {
            if {[catch {$S Add "$pre $i"}]} { set ok 0; break }
        }
        if {$ok && [::esl::set_count $S $qry $setid $entity] == $n} { return "per_id: $pre" }
    }
    catch {$S Clear}
    return ""
}

# Chunk selection sets over sorted ids (built once, reused by all frames): list of {setid handle n}.
# One chunk (or id selection not working) -> the whole part set.
proc ::esl::make_chunks {M qry entity ids size whole what} {
    variable chunk_how
    set n [llength $ids]
    if {$n <= $size} {
        dict set chunk_how $what "single"
        return [list [list $whole "" $n]]
    }
    set out {}
    set k 0
    for {set i 0} {$i < $n} {incr i $size} {
        set part [lrange $ids $i [expr {$i + $size - 1}]]
        ::esl::step "$what chunk $k selection"
        set sid [$M AddSelectionSet $entity]
        set h esl_ch_${what}_${k}_$::esl::sfx
        $M GetSelectionSetHandle $h $sid
        set how [::esl::select_ids $h $qry $sid $entity $part]
        if {$how eq ""} {
            ::esl::warn "$what: selection by id failed (chunk $k); querying the whole part set at once"
            dict set chunk_how $what "whole (id selection failed)"
            return [list [list $whole "" $n]]
        }
        lappend out [list $sid $h [llength $part]]
        incr k
    }
    dict set chunk_how $what "[llength $out] chunks, $how"
    return $out
}

proc ::esl::sim_time {sims fi} {
    set t [::esl::label_time [lindex $sims $fi]]
    if {$t eq "" || ![string is double -strict $t]} {
        ::esl::note "no time in simulation label; time = frame index"
        set t $fi
    }
    return $t
}

proc ::esl::set_sim {res post fi} {
    ::esl::step "frame $fi SetCurrentSimulation"
    $res SetCurrentSimulation $fi
    catch {$post Draw}
}

proc ::esl::jints {l} { return "\[[join $l ,]\]" }


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
proc ::esl::open_csv {path header} {
    set fh [open $path w]
    fconfigure $fh -translation lf -encoding ascii -buffering full
    puts $fh $header
    return $fh
}

proc ::esl::write_done {out ok extra {raw ""}} {
    variable warnings
    variable h3d
    ::esl::flush_notes
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
    set xargs [::esl::extra_args $arglist]
    if {$a(input) ne ""} { set h3d [::esl::fwd $a(input)] }
    ::esl::collect_env $h3d
    if {$a(output) eq ""} { ::esl::fail INPUT_INVALID "missing -output <dir>" }
    set out [::esl::fwd $a(output)]
    set ::esl::outdir $out
    ::esl::step mkdir_output
    file mkdir $out
    ::esl::step backup_outputs
    ::esl::backup_outputs $out
    set ::esl::plog_on 1
    ::esl::plog "extract start: [file tail $a(input)] -> $out"
    ::esl::step check_input
    if {$a(input) eq ""} { ::esl::fail INPUT_INVALID "missing -input <h3d>" }
    if {![file isfile $h3d]} { ::esl::fail TOOL_OUTPUT_MISSING "h3d not found: $h3d" }
    ::esl::step read_request
    set cfg [::esl::read_config [::esl::fwd $a(config)] $xargs]
    set spec [string trim $a(part)]
    if {$spec eq ""} { set spec [dict get $cfg part_id] }
    if {$spec eq ""} { set spec [dict get $cfg part_title] }
    set ::esl::part_spec $spec
    set sc [dict get $cfg subcase]
    set dtype [dict get $cfg disp_type]
    set ::esl::sys_req [dict get $cfg strain_system]
    if {[lsearch -exact {elemental analysis global none} [string tolower $::esl::sys_req]] < 0} {
        ::esl::fail INPUT_INVALID "strain_system must be elemental|analysis|global|none: $::esl::sys_req"
    }
    set rtol [dict get $cfg reach_rtol]
    set top_n [dict get $cfg top_n]
    set hot_k [dict get $cfg hot_k]
    if {$hot_k > 1000} {
        ::esl::warn "hot_k $hot_k is large: history.csv grows to n_frames x |H| rows (|H| <= 2*hot_k)"
    }
    set csize [dict get $cfg chunk]
    set efields [::esl::elem_fields $cfg]
    set nreal [llength $efields]
    set epad [expr {6 - $nreal}]
    if {$epad > 0} { ::esl::warn "epsp_type empty: plastic strain written as 0" }
    set dfields {}
    foreach c [dict get $cfg disp_comps] { lappend dfields [list $dtype $c "" 0] }

    # ---- session / model (every call is a named step; see done.json failed_step / api)
    ::esl::progress "open session and load model/results (can take minutes for a large h3d)"
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
    set last [expr {$nsim - 1}]
    set dtypes [::esl::do GetDataTypeList {$res GetDataTypeList $sc}]
    ::esl::step check_results
    ::esl::check_result $res $sc $dtypes [dict get $cfg strain_type] \
        [concat [list [dict get $cfg vm_comp]] [dict get $cfg strain_comps]] [dict get $cfg strain_layer]
    if {$nreal == 6} {
        ::esl::check_result $res $sc $dtypes [dict get $cfg epsp_type] [list [dict get $cfg epsp_comp]] [dict get $cfg epsp_layer]
    }
    ::esl::check_result $res $sc $dtypes $dtype [dict get $cfg disp_comps] ""
    set con esl_con_$x
    ::esl::do GetContourCtrlHandle {$res GetContourCtrlHandle $con}

    # ---- selections: part elements / nodes, chunk sets (built once)
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
    ::esl::step element_ids
    set eids [::esl::set_ids $eset $qry $eset_id element]
    ::esl::step node_ids
    set nids [::esl::set_ids $nset $qry $nset_id node]
    ::esl::progress "part $pid ($ptitle): [llength $eids] elements, [llength $nids] nodes, $nsim frames"
    set echunks [::esl::make_chunks $model $qry element $eids $csize $eset_id elem]
    set nchunks [::esl::make_chunks $model $qry node $nids $csize $nset_id node]
    set ne_ch [llength $echunks]
    set nn_ch [llength $nchunks]

    # ---- frames.csv (all frames) and model.csv (frame 0 node coordinates, streamed)
    ::esl::step write_frames
    set ffr [::esl::open_csv [file join $out frames.csv] "frame_index,time"]
    for {set fi 0} {$fi < $nsim} {incr fi} { puts $ffr "$fi,[::esl::num [::esl::sim_time $sims $fi]]" }
    close $ffr
    ::esl::set_sim $res $post 0
    ::esl::step "model.csv node.coords"
    set fmo [::esl::open_csv [file join $out model.csv] "node_id,x0,y0,z0"]
    set nnode 0
    ::esl::each_rec $qry $nset_id "node.id node.coords" rec {
        if {[llength $rec] >= 4 && [string is integer -strict [lindex $rec 0]] \
                && [string is double -strict [lindex $rec 1]] && [string is double -strict [lindex $rec 2]] \
                && [string is double -strict [lindex $rec 3]]} {
            puts $fmo "[lindex $rec 0],[::esl::num [lindex $rec 1]],[::esl::num [lindex $rec 2]],[::esl::num [lindex $rec 3]]"
            incr nnode
        }
    }
    close $fmo

    # ---- pass A: last frame, all part elements (chunked) -> final.csv, running top hot_k
    set t0 [::esl::ms]
    ::esl::progress "pass A start (frame $last, $ne_ch element chunks)"
    ::esl::set_sim $res $post $last
    set fa [::esl::open_csv [file join $out final.csv] "elem_id,vm_hv,exx,eyy,ezz,exy,epsp"]
    set topvm {}
    set topep {}
    set nelem 0
    set miss 0
    set ci 0
    foreach ch $echunks {
        lassign $ch sid h cnt
        incr ci
        ::esl::progress "pass A (frame $last) elements chunk $ci/$ne_ch ($cnt)"
        set acc [::esl::collect $con $qry $sid element $efields "pass A frame $last chunk $ci"]
        set top [dict create vm {} ep {}]
        lassign [::esl::emit $fa "" $acc $nreal $epad top] n m
        incr nelem $n
        incr miss $m
        set topvm [::esl::topk [concat $topvm [dict get $top vm]] $hot_k]
        set topep [::esl::topk [concat $topep [dict get $top ep]] $hot_k]
        unset acc top
    }
    close $fa
    if {$nelem == 0} { ::esl::fail H3D_MISSING_RESULT "pass A: no element values at frame $last" }
    if {$miss > 0} { ::esl::warn "pass A: $miss elements without all values skipped" }
    lappend ::esl::passes "\"A\":\{\"frame\":$last,\"rows\":$nelem,\"chunks\":$ne_ch,\"seconds\":[::esl::secs $t0]\}"
    ::esl::progress "pass A done ([::esl::secs $t0] s)"

    # ---- pass B: every frame, hot set H -> history.csv; first-reach candidate frames D
    set t0 [::esl::ms]
    ::esl::progress "pass B start ($nsim frames)"
    set hids {}
    foreach p [concat $topvm $topep] { lappend hids [lindex $p 0] }
    set hids [lsort -integer -unique $hids]
    set nh [llength $hids]
    set keep [dict create]
    foreach id $hids { dict set keep $id 1 }
    set hmode "none"
    set hsets {}
    if {$nh > 0} {
        ::esl::step hot_selection
        set hsid [$model AddSelectionSet element]
        set hh esl_hset_$x
        $model GetSelectionSetHandle $hh $hsid
        set hmode [::esl::select_ids $hh $qry $hsid element $hids]
        if {$hmode eq ""} {
            set hmode "filter over element chunks"
            ::esl::warn "hot set: selection by id failed; pass B queries all part elements per frame and keeps H"
            set hsets $echunks
        } else {
            set hsets [list [list $hsid $hh $nh]]
        }
    }
    set fh [::esl::open_csv [file join $out history.csv] "frame_index,elem_id,vm_hv,exx,eyy,ezz,exy,epsp"]
    set hvm [dict create]
    set hep [dict create]
    set hrows 0
    if {$nh > 0} {
        for {set fi 0} {$fi < $nsim} {incr fi} {
            ::esl::set_sim $res $post $fi
            ::esl::progress "pass B frame [expr {$fi + 1}]/$nsim ($nh elements)"
            set acc [dict create]
            foreach ch $hsets {
                set acc [dict merge $acc [::esl::collect $con $qry [lindex $ch 0] element $efields "pass B frame $fi" $keep]]
            }
            set zeros [string repeat ",0" $epad]
            foreach id $hids {
                if {![dict exists $acc $id] || [llength [dict get $acc $id]] != $nreal} {
                    ::esl::fail H3D_MISSING_RESULT "pass B frame $fi: no values for hot element $id"
                }
                set vs [dict get $acc $id]
                set o {}
                foreach v $vs { lappend o [format $::esl::numfmt $v] }
                puts $fh "$fi,$id,[join $o ,]$zeros"
                incr hrows
                dict lappend hvm $id [lindex $vs 0]
                dict lappend hep $id [expr {$nreal == 6 ? [lindex $vs 5] : 0}]
            }
            unset acc
        }
    } else {
        ::esl::warn "hot set H is empty (no positive final vonMises / plastic strain)"
    }
    close $fh
    set cand_vm {{} {}}
    set cand_ep {{} {}}
    if {$nh > 0} {
        set cand_vm [::esl::cand_frames $hvm $hids $rtol $top_n]
        set cand_ep [::esl::cand_frames $hep $hids $rtol $top_n]
    }
    set D [lsort -integer -unique [concat [lindex $cand_vm 0] [lindex $cand_ep 0]]]
    if {[llength $D] == 0} {
        set D [list $last]
        ::esl::warn "no candidate frame from H; D = last frame $last"
    }
    lappend ::esl::passes "\"B\":\{\"frames\":$nsim,\"n_hot\":$nh,\"rows\":$hrows,\"hot_selection\":[::esl::jstr $hmode],\"seconds\":[::esl::secs $t0]\}"
    ::esl::progress "pass B done ([::esl::secs $t0] s)"
    ::esl::progress "candidate frames: max_strain [lindex $cand_vm 0], plastic_strain [lindex $cand_ep 0] -> D = $D"

    # ---- pass C: candidate frames D, all part elements and nodes (chunked)
    #      + previous frames P (f-1 >= 0 of each f in D): all part elements only (no displacement).
    #      Frames of P that are already in D are written once (as D frames).
    set P {}
    foreach fi $D {
        if {$fi > 0} { lappend P [expr {$fi - 1}] }
    }
    set P [lsort -integer -unique $P]
    set Pextra {}
    foreach fi $P {
        if {[lsearch -exact -integer $D $fi] < 0} { lappend Pextra $fi }
    }
    set CF [lsort -integer -unique [concat $D $Pextra]]
    set t0 [::esl::ms]
    ::esl::progress "pass C start ([llength $CF] frames)"
    set fs [::esl::open_csv [file join $out strain_frames.csv] "frame_index,elem_id,vm_hv,exx,eyy,ezz,exy,epsp"]
    set fds [::esl::open_csv [file join $out disp.csv] "frame_index,node_id,ux,uy,uz"]
    set srows 0
    set drows 0
    set k 0
    foreach fi $CF {
        incr k
        set isD [expr {[lsearch -exact -integer $D $fi] >= 0}]
        set tag [expr {$isD ? "" : " (prev)"}]
        ::esl::set_sim $res $post $fi
        set ci 0
        foreach ch $echunks {
            incr ci
            ::esl::progress "pass C frame $fi$tag ($k/[llength $CF]) elements chunk $ci/$ne_ch"
            set acc [::esl::collect $con $qry [lindex $ch 0] element $efields "pass C frame $fi chunk $ci"]
            lassign [::esl::emit $fs "$fi," $acc $nreal $epad] n m
            incr srows $n
            if {$m > 0} { ::esl::note "pass C: elements without all values skipped" $m }
            unset acc
        }
        if {!$isD} { continue }
        set ci 0
        foreach ch $nchunks {
            incr ci
            ::esl::progress "pass C frame $fi ($k/[llength $CF]) nodes chunk $ci/$nn_ch"
            set acc [::esl::collect $con $qry [lindex $ch 0] node $dfields "pass C frame $fi chunk $ci"]
            lassign [::esl::emit $fds "$fi," $acc 3 0] n m
            incr drows $n
            if {$m > 0} { ::esl::note "pass C: nodes without all displacement values skipped" $m }
            unset acc
        }
    }
    close $fs
    close $fds
    lappend ::esl::passes "\"C\":\{\"frames\":[::esl::jints $D],\"prev_frames\":[::esl::jints $P],\"strain_frames\":[::esl::jints $CF],\"rows_strain\":$srows,\"rows_disp\":$drows,\"elem_chunks\":$ne_ch,\"node_chunks\":$nn_ch,\"seconds\":[::esl::secs $t0]\}"
    ::esl::progress "pass C done ([::esl::secs $t0] s)"
    ::esl::progress "disp done"

    ::esl::step CloseStack
    catch {hwi CloseStack}
    ::esl::step write_done
    set ::esl::cur_step "done"
    lappend ::esl::steps_done write_csv
    set ch_json {}
    dict for {k2 v2} $::esl::chunk_how { lappend ch_json "[::esl::jstr $k2]:[::esl::jstr $v2]" }
    if {[::esl::write_done $out 1 [list part_id $pid part_title [::esl::jstr $ptitle] \
        part_spec [::esl::jstr $spec] n_frames $nsim n_elems $nelem n_nodes $nnode n_hot $nh \
        hot_k $hot_k top_n $top_n reach_rtol [::esl::num $rtol] \
        candidate_frames "\{\"max_strain\":[::esl::jints [lindex $cand_vm 0]],\"plastic_strain\":[::esl::jints [lindex $cand_ep 0]]\}" \
        candidate_elems "\{\"max_strain\":[::esl::jints [lindex $cand_vm 1]],\"plastic_strain\":[::esl::jints [lindex $cand_ep 1]]\}" \
        frames_D [::esl::jints $D] prev_frames [::esl::jints $P] strain_frames [::esl::jints $CF] \
        passes "\{[join $::esl::passes ,]\}" chunk $csize chunks "\{[join $ch_json ,]\}" \
        subcase [::esl::jstr $sc] elem_selection [::esl::jstr [lindex $esel 0]] \
        node_selection [::esl::jstr [lindex $nsel 0]] \
        strain_type [::esl::jstr [dict get $cfg strain_type]] strain_layer [::esl::jstr [dict get $cfg strain_layer]] \
        strain_comps [::esl::jarr [dict get $cfg strain_comps]] vm_comp [::esl::jstr [dict get $cfg vm_comp]] \
        epsp_type [::esl::jstr [dict get $cfg epsp_type]] epsp_layer [::esl::jstr [dict get $cfg epsp_layer]] \
        disp_type [::esl::jstr $dtype] exy [::esl::jstr "raw (as stored in h3d)"] \
        disp_value_format [::esl::jstr $::esl::numfmt] value_format [::esl::jstr $::esl::numfmt] \
        strain_system [::esl::jstr $::esl::sys_req] \
        strain_system_call [::esl::jstr $::esl::sys_applied] \
        backup_dir [::esl::jstr [::esl::fwd $::esl::backup_dir]]]] eq ""} {
        error "done.json could not be written"
    }
    set ::esl::written 1
    ::esl::progress "extract done: $nelem elements, $nnode nodes, H $nh, D $D, prev $P"
    ::esl::plog_close
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
                part_spec [::esl::jstr $::esl::part_spec] part_id $::esl::pidj \
                passes "\{[join $::esl::passes ,]\}"] \
                [::esl::diag_members $::esl::err $::esl::opts]} ::esl::werr]} {
            puts stderr "ESL: done.json not written: $::esl::werr"
        }
    }
    ::esl::plog "FAILED at step '$::esl::cur_step': $::esl::code: [::esl::short $::esl::err 200]"
    ::esl::plog_close
    puts stderr "ESL extract failed at step '$::esl::cur_step': $::esl::code: $::esl::err"
    set ::esl::rc 1
}
if {![info exists ::ESL_NO_EXIT]} { exit $::esl::rc }
