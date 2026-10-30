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
#   model.csv          node_id,x0,y0,z0,cx,cy,cz,dx,dy,dz               (part nodes: x0 = initial coords
#                      = frame-0 node.coords (cx..) - frame-0 displacement (dx..))
#   elems.csv          elem_id,n1,n2,n3,n4                              (part element connectivity, triangles
#                      n4 = 0; done.json "elems_ok" false and no file if the query is not available)
#   final.csv         elem_id,vm_hv,exx,eyy,ezz,exy,epsp               (A)
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
# Strain source fallback (contract esl_strain_fallback.md, v0.12.1): unless strain_type or epsp_type is given
# in request.txt (then: Max_Strain only, as before), the strain result is the FIRST source of
# strain_sources (default "max_strain plastic_strain strain_tensor max_stress") whose result type,
# components and layers are all in the subcase. Name candidates ('|' separated): names_<source>,
# comp_xx comp_yy comp_zz comp_xy, vm_comps, scalar_comps, layer_exclude (strain_tensor layers left out).
#   max_strain / plastic_strain / max_stress: max-hold, three passes as above (mode "maxhold");
#     plastic_strain: vm_hv = epsp = Plastic Strain, exx..exy = 0; max_stress: vm_hv = stress vonMises.
#   strain_tensor (instantaneous Strain, per layer): mode "dump" -- no ranking here; every frame x part
#     element x layer -> strain_raw.csv frame_index,elem_id,layer,vm_hv,exx,eyy,ezz,exy,epsp (layer = position
#     in done.json strain_layers) and every frame x part node -> disp.csv. The Python core rebuilds the
#     max-hold series, H, D, P (final/history/strain_frames are not written).
#   Plastic strain (epsp column) is read when a plastic_strain name exists, else 0 + warning H3D_NO_EPSP.
#   No source -> H3D_NO_STRAIN_SOURCE (failed_step check_results, done.json strain_tried).
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
        elem_selection "" node_selection "" strain_system "elemental" \
        prev_file "" frame0_pass 0 cum_min_incr 1e-5 \
        strain_sources "max_strain plastic_strain strain_tensor max_stress" \
        names_max_strain "Max_Strain" names_plastic_strain "Plastic Strain|Plastic_Strain" \
        names_strain_tensor "Strain" names_max_stress "Max_Stress" \
        comp_xx "XX" comp_yy "YY" comp_zz "ZZ" comp_xy "XY" vm_comps "vonMises|von Mises" \
        scalar_comps "Scalar value|Scalar" layer_exclude "Max|Min" dump_max_bytes 0 dump_free_bytes ""]
    set cfg [::esl::read_request $path $defaults]
    # strain_type / epsp_type written in request.txt -> Max_Strain only (no fallback, backward compatible)
    set ::esl::forced 0
    if {$path ne "" && [file isfile $path]} {
        set raw [::esl::read_request $path [dict create]]
        if {[dict exists $raw strain_type] || [dict exists $raw epsp_type]} { set ::esl::forced 1 }
    }
    set srcs [dict get $cfg strain_sources]
    if {[llength $srcs] == 0} { ::esl::fail INPUT_INVALID "strain_sources is empty" }
    foreach s $srcs {
        if {[lsearch -exact {max_strain plastic_strain strain_tensor max_stress} $s] < 0} {
            ::esl::fail INPUT_INVALID "strain_sources: unknown source '$s'"
        }
        if {[llength [lsearch -all -exact $srcs $s]] > 1} { ::esl::fail INPUT_INVALID "strain_sources: '$s' twice" }
    }
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
    set f0 [dict get $cfg frame0_pass]
    if {$f0 ne "0" && $f0 ne "1"} { ::esl::fail INPUT_INVALID "frame0_pass must be 0 or 1: $f0" }
    set mi [dict get $cfg cum_min_incr]
    if {![string is double -strict $mi] || $mi < 0} { ::esl::fail INPUT_INVALID "cum_min_incr must be >= 0: $mi" }
    return $cfg
}

# Cumulative scene (optional request key prev_file): CSV elem_id,prev_epsp,prev_eq written by the worker
# (previous run plastic strain of the target part). Fills ::esl::prev_ep / ::esl::prev_eq dicts.
proc ::esl::read_prev {path} {
    if {![file isfile $path]} { ::esl::fail INPUT_INVALID "prev_file not found: $path" }
    set fh [open $path r]
    fconfigure $fh -encoding ascii
    set n 0
    set first 1
    while {[gets $fh line] >= 0} {
        set line [string trim $line]
        if {$line eq "" || [string index $line 0] eq "#"} { continue }
        if {$first} {
            set first 0
            if {![string is integer -strict [lindex [split $line ,] 0]]} { continue }
        }
        set r [split $line ,]
        if {[llength $r] < 3} { close $fh; ::esl::fail INPUT_INVALID "prev_file line needs 3 values: $line" }
        lassign $r id ep eq
        if {![string is integer -strict $id] || ![string is double -strict $ep] || ![string is double -strict $eq]} {
            close $fh
            ::esl::fail INPUT_INVALID "prev_file bad line: $line"
        }
        dict set ::esl::prev_ep $id $ep
        dict set ::esl::prev_eq $id $eq
        incr n
    }
    close $fh
    return $n
}

proc ::esl::prev_of {d id} {
    if {[dict exists $d $id]} { return [dict get $d $id] }
    return 0.0
}

# "+prev" D rule (cumulative scenes): elements ranked by final raw + prev (only raw final > min_incr),
# first-reach on the raw series. Returns {frames elems}.
proc ::esl::cand_frames_prev {hist ids rtol top_n prevd min_incr} {
    set pairs {}
    foreach id $ids {
        set v [lindex [dict get $hist $id] end]
        if {$v > $min_incr} { lappend pairs [list $id [expr {$v + [::esl::prev_of $prevd $id]}]] }
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

# ---- strain source selection (esl_strain_fallback.md 3)
# "a|b|c" -> {a b c} (candidates may contain blanks)
proc ::esl::cands {s} {
    set out {}
    foreach x [split $s |] {
        set x [string trim $x]
        if {$x ne ""} { lappend out $x }
    }
    return $out
}

# First candidate in avail: exact match first, then ignoring case, blanks and underscores. "" if none.
proc ::esl::match_name {avail cands} {
    foreach c $cands {
        if {[lsearch -exact $avail $c] >= 0} { return $c }
    }
    foreach c $cands {
        set n [::esl::norm_title $c]
        foreach a $avail {
            if {[::esl::norm_title $a] eq $n} { return $a }
        }
    }
    return ""
}

# Component / layer lists ("?" = the API did not answer: names are taken on trust).
proc ::esl::comp_list {res sc dt} {
    if {[catch {$res GetDataComponentList $sc $dt} l] || [llength $l] == 0} { return "?" }
    return $l
}
proc ::esl::layer_list {res sc dt} {
    if {[catch {$res GetLayerList $sc $dt} l] || [llength $l] == 0} { return "?" }
    return $l
}
proc ::esl::match_comp {have cands} {
    if {$have eq "?"} { return [lindex $cands 0] }
    return [::esl::match_name $have $cands]
}
proc ::esl::pick_layer {ls pref} {
    if {$ls eq "?"} { return "" }
    if {$pref ne "" && [lsearch -exact $ls $pref] >= 0} { return $pref }
    return [lindex $ls 0]
}

# Try the sources of cfg strain_sources in order. Returns a dict (source type mode layers vm comps scalar)
# of the first usable one; every rejected source is appended to ::esl::tried {source type reason}.
proc ::esl::pick_source {res sc dtypes cfg} {
    variable tried
    set tried {}
    foreach s [dict get $cfg strain_sources] {
        set dt [::esl::match_name $dtypes [::esl::cands [dict get $cfg names_$s]]]
        if {$dt eq ""} {
            lappend tried [list $s "" "result type not in subcase (candidates: [dict get $cfg names_$s])"]
            continue
        }
        set have [::esl::comp_list $res $sc $dt]
        set ls [::esl::layer_list $res $sc $dt]
        if {$s eq "plastic_strain"} {
            set c [::esl::match_comp $have [::esl::cands [dict get $cfg scalar_comps]]]
            if {$c eq ""} {
                lappend tried [list $s $dt "no scalar component ([dict get $cfg scalar_comps]) in: $have"]
                continue
            }
            return [dict create source $s type $dt mode maxhold layers [list [::esl::pick_layer $ls [dict get $cfg epsp_layer]]] \
                vm "" comps {} scalar $c]
        }
        set comps {}
        set miss {}
        foreach k {xx yy zz xy} {
            set c [::esl::match_comp $have [::esl::cands [dict get $cfg comp_$k]]]
            if {$c eq ""} { lappend miss "$k ([dict get $cfg comp_$k])" }
            lappend comps $c
        }
        set vm [::esl::match_comp $have [::esl::cands [dict get $cfg vm_comps]]]
        if {$vm eq "" && $s ne "strain_tensor"} { lappend miss "vonMises ([dict get $cfg vm_comps])" }
        if {[llength $miss] > 0} {
            lappend tried [list $s $dt "components missing: [join $miss {, }] (available: $have)"]
            continue
        }
        if {$s eq "strain_tensor"} {
            if {$ls eq "?"} {
                set lay [list ""]
            } else {
                set ex [::esl::cands [dict get $cfg layer_exclude]]
                set lay {}
                foreach l $ls {
                    if {[lsearch -exact $ex $l] < 0} { lappend lay $l }
                }
                if {[llength $lay] == 0} {
                    lappend tried [list $s $dt "no tensor layer left after excluding {$ex} (layers: $ls)"]
                    continue
                }
            }
            return [dict create source $s type $dt mode dump layers $lay vm $vm comps $comps scalar ""]
        }
        return [dict create source $s type $dt mode maxhold layers [list [::esl::pick_layer $ls [dict get $cfg strain_layer]]] \
            vm $vm comps $comps scalar ""]
    }
    set why {}
    foreach t $tried { lappend why "[lindex $t 0]: [lindex $t 2]" }
    ::esl::fail H3D_NO_STRAIN_SOURCE "no strain source in subcase $sc (tried: [join $why {; }]; available: $dtypes)"
}

# Plastic strain result for the epsp column: {type comp layer} or {} when the h3d has none.
proc ::esl::pick_epsp {res sc dtypes cfg} {
    set dt [::esl::match_name $dtypes [::esl::cands [dict get $cfg names_plastic_strain]]]
    if {$dt eq ""} { return {} }
    set c [::esl::match_comp [::esl::comp_list $res $sc $dt] [::esl::cands [dict get $cfg scalar_comps]]]
    if {$c eq ""} { return {} }
    return [list $dt $c [::esl::pick_layer [::esl::layer_list $res $sc $dt] [dict get $cfg epsp_layer]]]
}

proc ::esl::tried_json {} {
    variable tried
    set rows {}
    foreach t $tried {
        lassign $t s dt why
        set dj [expr {$dt eq "" ? "null" : [::esl::jstr $dt]}]
        lappend rows "\{\"source\":[::esl::jstr $s],\"type\":$dj,\"reason\":[::esl::jstr $why]\}"
    }
    return "\[[join $rows ,]\]"
}

# The 6 CSV values (vm_hv exx eyy ezz exy epsp) of an element record vs (field order of elem_fields):
# ::esl::row_map gives the field position per column, "z" = constant 0.
proc ::esl::six {vs} {
    set r {}
    foreach m $::esl::row_map {
        if {$m eq "z"} { lappend r 0 } else { lappend r [lindex $vs $m] }
    }
    return $r
}

# Dump pass (strain_tensor source): every frame, all part elements x layers -> strain_raw.csv, all part
# nodes -> disp.csv. No ranking (the core rebuilds the max-hold series). vm_hv = 0 when the type has no
# vonMises component, epsp = 0 when there is no plastic strain result.
proc ::esl::dump_pass {out res post con qry cfg src layers epsp_ok echunks nchunks dfields nsim} {
    set t0 [::esl::ms]
    set dt [dict get $src type]
    lassign [dict get $src comps] cxx cyy czz cxy
    set vm [dict get $src vm]
    set ne_ch [llength $echunks]
    set nn_ch [llength $nchunks]
    set nl [llength $layers]
    ::esl::progress "dump start ($nsim frames, $nl layers {$layers}, $ne_ch element chunks, $nn_ch node chunks)"
    set fr [::esl::open_csv [file join $out strain_raw.csv] "frame_index,elem_id,layer,vm_hv,exx,eyy,ezz,exy,epsp"]
    set fd [::esl::open_csv [file join $out disp.csv] "frame_index,node_id,ux,uy,uz"]
    set lf {}
    foreach L $layers {
        set f [list [list $dt $cxx $L 1] [list $dt $cyy $L 1] [list $dt $czz $L 1] [list $dt $cxy $L 1]]
        if {$vm ne ""} { lappend f [list $dt $vm $L 0] }
        lappend lf $f
    }
    set nt [expr {$vm ne "" ? 5 : 4}]
    set epf [list [list [dict get $cfg epsp_type] [dict get $cfg epsp_comp] [dict get $cfg epsp_layer] 0]]
    set srows 0
    set drows 0
    set miss 0
    for {set fi 0} {$fi < $nsim} {incr fi} {
        ::esl::set_sim $res $post $fi
        set ci 0
        foreach ch $echunks {
            incr ci
            ::esl::progress "dump frame [expr {$fi + 1}]/$nsim elements chunk $ci/$ne_ch"
            set ep [dict create]
            if {$epsp_ok} {
                set ep [::esl::collect $con $qry [lindex $ch 0] element $epf "dump frame $fi chunk $ci"]
            }
            set li 0
            foreach f $lf {
                set acc [::esl::collect $con $qry [lindex $ch 0] element $f "dump frame $fi chunk $ci layer $li"]
                dict for {id vs} $acc {
                    if {[llength $vs] != $nt} { incr miss; continue }
                    set e 0
                    if {$epsp_ok} {
                        if {![dict exists $ep $id]} { incr miss; continue }
                        set e [lindex [dict get $ep $id] 0]
                    }
                    lassign $vs xx yy zz xy v
                    if {$nt == 4} { set v 0 }
                    puts $fr "$fi,$id,$li,[::esl::num $v],[::esl::num $xx],[::esl::num $yy],[::esl::num $zz],[::esl::num $xy],[::esl::num $e]"
                    incr srows
                }
                unset acc
                incr li
            }
            unset ep
        }
        set ci 0
        foreach ch $nchunks {
            incr ci
            ::esl::progress "dump frame [expr {$fi + 1}]/$nsim nodes chunk $ci/$nn_ch"
            set acc [::esl::collect $con $qry [lindex $ch 0] node $dfields "dump frame $fi chunk $ci"]
            lassign [::esl::emit $fd "$fi," $acc 3 0] n m
            incr drows $n
            if {$m > 0} { ::esl::note "dump: nodes without all displacement values skipped" $m }
            unset acc
        }
    }
    close $fr
    close $fd
    if {$miss > 0} { ::esl::note "dump: element rows without all values skipped" $miss }
    if {$srows == 0} { ::esl::fail H3D_MISSING_RESULT "dump: no element values ($dt)" }
    lappend ::esl::passes "\"DUMP\":\{\"frames\":$nsim,\"layers\":$nl,\"rows_strain\":$srows,\"rows_disp\":$drows,\"elem_chunks\":$ne_ch,\"node_chunks\":$nn_ch,\"seconds\":[::esl::secs $t0]\}"
    ::esl::progress "dump done ([::esl::secs $t0] s, $srows element rows, $drows node rows)"
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
    # element rows (6 columns): values through ::esl::row_map (pads = 0, same text as before)
    set six [expr {$nreal + $pad == 6}]
    dict for {id vs} $acc {
        if {[llength $vs] != $nreal} { incr miss; continue }
        set o {}
        if {$six} {
            set vs [::esl::six $vs]
            foreach v $vs { lappend o [format $::esl::numfmt $v] }
            puts $fh "$prefix$id,[join $o ,]"
        } else {
            foreach v $vs { lappend o [format $::esl::numfmt $v] }
            puts $fh "$prefix$id,[join $o ,]$zeros"
        }
        incr n
        if {$topvar ne ""} {
            set v0 [lindex $vs 0]
            set v5 [lindex $vs 5]
            if {$v0 > 0} { dict lappend top vm [list $id $v0] }
            if {$v5 > 0} { dict lappend top ep [list $id $v5] }
            if {$::esl::has_prev} {
                if {$v0 > $::esl::min_incr} {
                    dict lappend top vmp [list $id [expr {$v0 + [::esl::prev_of $::esl::prev_eq $id]}]]
                }
                if {$v5 > $::esl::min_incr} {
                    dict lappend top epp [list $id [expr {$v5 + [::esl::prev_of $::esl::prev_ep $id]}]]
                }
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
    # cumulative scene (optional keys; absent -> unchanged behaviour)
    set ::esl::has_prev 0
    set ::esl::prev_ep [dict create]
    set ::esl::prev_eq [dict create]
    set ::esl::min_incr [dict get $cfg cum_min_incr]
    set prev_path [::esl::fwd [dict get $cfg prev_file]]
    set prev_n 0
    set prev_sha ""
    if {$prev_path ne ""} {
        ::esl::step read_prev
        set prev_n [::esl::read_prev $prev_path]
        set ::esl::has_prev 1
        if {![catch {package require sha256} ]} {
            catch {set prev_sha [::sha2::sha256 -hex -filename $prev_path]}
        }
        ::esl::progress "prev_file: $prev_n elements ([file tail $prev_path])"
    }
    set f0pass [dict get $cfg frame0_pass]
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
    # strain source (esl_strain_fallback.md 1/3): forced (strain_type/epsp_type in request) = Max_Strain only
    set ::esl::row_map {0 1 2 3 4 5}
    set ::esl::tried {}
    set smode maxhold
    set slayers {}
    set epsp_ok 1
    set src [dict create source max_strain type [dict get $cfg strain_type]]
    if {$::esl::forced} {
        ::esl::check_result $res $sc $dtypes [dict get $cfg strain_type] \
            [concat [list [dict get $cfg vm_comp]] [dict get $cfg strain_comps]] [dict get $cfg strain_layer]
        if {[dict get $cfg epsp_type] ne ""} {
            ::esl::check_result $res $sc $dtypes [dict get $cfg epsp_type] [list [dict get $cfg epsp_comp]] [dict get $cfg epsp_layer]
        } else {
            set epsp_ok 0
            ::esl::warn "epsp_type empty: plastic strain written as 0"
        }
        set slayers [list [dict get $cfg strain_layer]]
    } else {
        set src [::esl::pick_source $res $sc $dtypes $cfg]
        set smode [dict get $src mode]
        set slayers [dict get $src layers]
        set ep [::esl::pick_epsp $res $sc $dtypes $cfg]
        if {[dict get $src source] eq "plastic_strain"} {
            set ep [list [dict get $src type] [dict get $src scalar] [lindex $slayers 0]]
        }
        if {[llength $ep] == 0} {
            set epsp_ok 0
            dict set cfg epsp_type ""
            ::esl::warn "H3D_NO_EPSP: no plastic strain result ([dict get $cfg names_plastic_strain]) in subcase $sc; epsp = 0"
        } else {
            dict set cfg epsp_type [lindex $ep 0]
            dict set cfg epsp_comp [lindex $ep 1]
            dict set cfg epsp_layer [lindex $ep 2]
        }
        dict set cfg strain_type [dict get $src type]
        if {[dict get $src source] eq "plastic_strain"} {
            dict set cfg strain_layer [lindex $slayers 0]
        } else {
            dict set cfg strain_comps [dict get $src comps]
            dict set cfg vm_comp [dict get $src vm]
            dict set cfg strain_layer [lindex $slayers 0]
        }
        set tl {}
        foreach t $::esl::tried { lappend tl "[lindex $t 0] ([lindex $t 2])" }
        ::esl::progress "strain source: [dict get $src source] ([dict get $src type], $smode, layers {$slayers})[expr {[llength $tl] ? "; skipped: [join $tl {; }]" : ""}]"
    }
    if {[dict get $src source] eq "plastic_strain"} {
        # vm_hv = epsp = Plastic Strain, exx..exy = 0 (esl_strain_fallback.md 3)
        set efields [list [list [dict get $cfg epsp_type] [dict get $cfg epsp_comp] [dict get $cfg epsp_layer] 0]]
        set ::esl::row_map {0 z z z z 0}
    } else {
        set efields [::esl::elem_fields $cfg]
        if {[llength $efields] < 6} { set ::esl::row_map {0 1 2 3 4 z} }
    }
    set nreal [llength $efields]
    set epad [expr {6 - $nreal}]
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
    # model.csv: initial (undeformed) coordinates x0 = node.coords - frame-0 Displacement.
    # node.coords is the coordinate of the current frame (deformed when frame 0 has a displacement,
    # e.g. a drop model whose first stored state is t > 0 or carries an initial rigid motion), so the
    # frame-0 displacement (disp_type / disp_comps) is read for the same node chunk and subtracted.
    # Raw coords (cx,cy,cz) and frame-0 displacement (dx,dy,dz) are kept as diagnostic columns.
    ::esl::set_sim $res $post 0
    set t_f0 [::esl::sim_time $sims 0]
    ::esl::progress "model.csv: frame 0 (time $t_f0) node.coords - $dtype ($nn_ch node chunks)"
    set fmo [::esl::open_csv [file join $out model.csv] "node_id,x0,y0,z0,cx,cy,cz,dx,dy,dz"]
    set nnode 0
    set nod0 0
    set d0max 0.0
    set d0ok 1
    set ci 0
    foreach ch $nchunks {
        incr ci
        set d0 [dict create]
        if {$d0ok} {
            if {[catch {::esl::collect $con $qry [lindex $ch 0] node $dfields "model.csv frame 0 chunk $ci"} acc]} {
                set d0ok 0
                ::esl::warn "model.csv: frame 0 $dtype not available ([::esl::short $acc 200]); x0 = node.coords of frame 0 (dx,dy,dz = 0)"
            } else {
                set d0 $acc
            }
            unset -nocomplain acc
        }
        ::esl::step "model.csv node.coords chunk $ci"
        ::esl::each_rec $qry [lindex $ch 0] "node.id node.coords" rec {
            if {[llength $rec] >= 4 && [string is integer -strict [lindex $rec 0]] \
                    && [string is double -strict [lindex $rec 1]] && [string is double -strict [lindex $rec 2]] \
                    && [string is double -strict [lindex $rec 3]]} {
                set id [lindex $rec 0]
                if {[dict exists $d0 $id] && [llength [dict get $d0 $id]] == 3} {
                    lassign [dict get $d0 $id] dx dy dz
                } else {
                    set dx 0.0; set dy 0.0; set dz 0.0
                    if {$d0ok} { incr nod0 }
                }
                lassign [lrange $rec 1 3] cx cy cz
                set dm [expr {sqrt($dx*$dx + $dy*$dy + $dz*$dz)}]
                if {$dm > $d0max} { set d0max $dm }
                puts $fmo "$id,[::esl::num [expr {$cx - $dx}]],[::esl::num [expr {$cy - $dy}]],[::esl::num [expr {$cz - $dz}]],[::esl::num $cx],[::esl::num $cy],[::esl::num $cz],[::esl::num $dx],[::esl::num $dy],[::esl::num $dz]"
                incr nnode
            }
        }
        unset d0
    }
    close $fmo
    if {$nod0 > 0} { ::esl::warn "model.csv: $nod0 nodes without frame 0 $dtype (x0 = node.coords)" }
    ::esl::progress "model.csv done: $nnode nodes, frame 0 |disp| max [::esl::num $d0max]"

    # ---- elems.csv: part element -> node ids (model identity check in pack: same node ids per element).
    # The query field name is tried in order on the first element chunk (UNVERIFIED names); a record is
    # {id n1 n2 n3 [n4]} (nested list or comma separated). Not available -> warning, done.json elems_ok:false
    # and no elems.csv (pack then skips the connectivity check).
    set t0 [::esl::ms]
    ::esl::progress "elems.csv: element connectivity ($ne_ch element chunks)"
    set fel [::esl::open_csv [file join $out elems.csv] "elem_id,n1,n2,n3,n4"]
    set conn_cands [list "element.id element.connectivity" "element.id element.nodes" "element.id element.node_ids"]
    set conn_q ""
    set conn_err {}
    set nconn 0
    set nconn_bad 0
    set elems_ok 1
    set ci 0
    foreach ch $echunks {
        incr ci
        ::esl::step "elems.csv connectivity chunk $ci"
        if {$conn_q eq ""} { set tries $conn_cands } else { set tries [list $conn_q] }
        set got 0
        foreach q $tries {
            set rows {}
            set nbad 0
            if {[catch {
                ::esl::each_rec $qry [lindex $ch 0] $q rec {
                    set r [string map {, " "} [join $rec " "]]
                    set ok [expr {[llength $r] == 4 || [llength $r] == 5}]
                    if {$ok} {
                        foreach v $r { if {![string is integer -strict $v]} { set ok 0; break } }
                    }
                    if {$ok} {
                        if {[llength $r] == 4} { lappend r 0 }
                        lappend rows [join $r ,]
                    } else {
                        incr nbad
                    }
                }
            } e]} {
                lappend conn_err "$q: [::esl::short $e 120]"
                continue
            }
            if {$conn_q eq "" && [llength $rows] == 0} {
                lappend conn_err "$q: no usable rows ($nbad unparsed)"
                continue
            }
            set conn_q $q
            set got 1
            foreach r $rows { puts $fel $r }
            incr nconn [llength $rows]
            incr nconn_bad $nbad
            break
        }
        unset -nocomplain rows
        if {!$got} { set elems_ok 0; break }
    }
    close $fel
    if {$elems_ok && ($nconn == 0 || $nconn_bad > 0)} {
        set elems_ok 0
        lappend conn_err "$nconn rows, $nconn_bad records not {id n1 n2 n3 \[n4\]}"
    }
    if {!$elems_ok} {
        catch {file delete [file join $out elems.csv]}
        ::esl::warn "elems.csv: element connectivity not available ([::esl::short [join $conn_err {; }] 300]); rad/h3d connectivity check skipped"
        ::esl::progress "elems.csv skipped: connectivity query failed"
    } else {
        ::esl::progress "elems.csv done: $nconn elements (query '$conn_q', [::esl::secs $t0] s)"
    }

    # ---- strain source members of done.json (esl_strain_fallback.md 3)
    set ::esl::src_members [list strain_source [::esl::jstr [dict get $src source]] \
        strain_source_type [::esl::jstr [dict get $cfg strain_type]] strain_layers [::esl::jarr $slayers] \
        strain_mode [::esl::jstr $smode] strain_tried [::esl::tried_json] \
        epsp_available [expr {$epsp_ok ? "true" : "false"}]]

    # ---- dump mode (strain_tensor: instantaneous values) -> strain_raw.csv + disp.csv, every frame
    if {$smode eq "dump"} {
        # size estimate before writing (same formula as esl.io.results_csv.dump_estimate_bytes: 160 B per
        # strain_raw row, 90 B per disp row; measured max 157 B / 85 B)
        set est [expr {wide($nsim) * (wide([llength $eids]) * [llength $slayers] * 160 + wide([llength $nids]) * 90)}]
        set dmax [dict get $cfg dump_max_bytes]
        set dfree [dict get $cfg dump_free_bytes]
        ::esl::progress "dump size estimate: $est bytes (limit $dmax, free [expr {$dfree eq "" ? "?" : $dfree}])"
        if {[string is wide -strict $dmax] && $dmax > 0 && $est > $dmax} {
            ::esl::fail STRAIN_DUMP_TOO_LARGE "Strain tensor dump estimate $est bytes > dump_max_bytes $dmax ($nsim frames x [llength $eids] elements x [llength $slayers] layers): add /H3D/ELEM/TENS/STRAIN/TMAX (or /H3D/SHELL/TENS/STRAIN/TMAX) to the deck"
        }
        if {[string is wide -strict $dfree] && $est > $dfree} {
            ::esl::fail INSUFFICIENT_STORAGE "Strain tensor dump estimate $est bytes > free space $dfree bytes in the output folder"
        }
        ::esl::dump_pass $out $res $post $con $qry $cfg $src $slayers $epsp_ok $echunks $nchunks $dfields $nsim
        ::esl::step CloseStack
        catch {hwi CloseStack}
        ::esl::step write_done
        set ::esl::cur_step "done"
        lappend ::esl::steps_done write_csv
        set ch_json {}
        dict for {k2 v2} $::esl::chunk_how { lappend ch_json "[::esl::jstr $k2]:[::esl::jstr $v2]" }
        set dcum "null"
        if {$::esl::has_prev || $f0pass eq "1"} {
            set dcum "\{\"prev_file\":[::esl::jstr $prev_path],\"prev_file_sha256\":[expr {$prev_sha eq "" ? "null" : [::esl::jstr $prev_sha]}],\"prev_n\":$prev_n,\"frame0\":[expr {$f0pass eq "1" ? "true" : "false"}],\"min_incr\":[::esl::num $::esl::min_incr]\}"
        }
        if {[::esl::write_done $out 1 [list part_id $pid part_title [::esl::jstr $ptitle] \
            part_spec [::esl::jstr $spec] n_frames $nsim \
            frame0_time [::esl::num $t_f0] model_coords [::esl::jstr "coords_minus_disp_frame0"] \
            frame0_disp_max [::esl::num $d0max] frame0_disp_ok [expr {$d0ok ? "true" : "false"}] \
            elems_ok [expr {$elems_ok ? "true" : "false"}] elems_query [::esl::jstr $conn_q] n_conn $nconn \
            n_elems [llength $eids] n_nodes $nnode \
            hot_k $hot_k top_n $top_n reach_rtol [::esl::num $rtol] \
            passes "\{[join $::esl::passes ,]\}" chunk $csize chunks "\{[join $ch_json ,]\}" \
            subcase [::esl::jstr $sc] elem_selection [::esl::jstr [lindex $esel 0]] \
            node_selection [::esl::jstr [lindex $nsel 0]] \
            strain_type [::esl::jstr [dict get $cfg strain_type]] strain_layer [::esl::jstr [lindex $slayers 0]] \
            strain_comps [::esl::jarr [dict get $src comps]] vm_comp [::esl::jstr [dict get $src vm]] \
            epsp_type [::esl::jstr [dict get $cfg epsp_type]] epsp_layer [::esl::jstr [dict get $cfg epsp_layer]] \
            disp_type [::esl::jstr $dtype] exy [::esl::jstr "raw (as stored in h3d)"] \
            disp_value_format [::esl::jstr $::esl::numfmt] value_format [::esl::jstr $::esl::numfmt] \
            strain_system [::esl::jstr $::esl::sys_req] \
            strain_system_call [::esl::jstr $::esl::sys_applied] \
            backup_dir [::esl::jstr [::esl::fwd $::esl::backup_dir]] dump_cumulative $dcum \
            {*}$::esl::src_members]] eq ""} {
            error "done.json could not be written"
        }
        set ::esl::written 1
        ::esl::progress "extract done: dump mode ($nsim frames, layers {$slayers}), $nnode nodes"
        ::esl::plog_close
        return
    }

    # ---- pass A: last frame, all part elements (chunked) -> final.csv, running top hot_k
    set t0 [::esl::ms]
    ::esl::progress "pass A start (frame $last, $ne_ch element chunks)"
    ::esl::set_sim $res $post $last
    set fa [::esl::open_csv [file join $out final.csv] "elem_id,vm_hv,exx,eyy,ezz,exy,epsp"]
    set topvm {}
    set topep {}
    set topvmp {}
    set topepp {}
    set nelem 0
    set miss 0
    set ci 0
    foreach ch $echunks {
        lassign $ch sid h cnt
        incr ci
        ::esl::progress "pass A (frame $last) elements chunk $ci/$ne_ch ($cnt)"
        set acc [::esl::collect $con $qry $sid element $efields "pass A frame $last chunk $ci"]
        set top [dict create vm {} ep {} vmp {} epp {}]
        lassign [::esl::emit $fa "" $acc $nreal $epad top] n m
        incr nelem $n
        incr miss $m
        set topvm [::esl::topk [concat $topvm [dict get $top vm]] $hot_k]
        set topep [::esl::topk [concat $topep [dict get $top ep]] $hot_k]
        if {$::esl::has_prev} {
            set topvmp [::esl::topk [concat $topvmp [dict get $top vmp]] $hot_k]
            set topepp [::esl::topk [concat $topepp [dict get $top epp]] $hot_k]
        }
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
    foreach p [concat $topvm $topep $topvmp $topepp] { lappend hids [lindex $p 0] }
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
                set vs [::esl::six [dict get $acc $id]]
                set o {}
                foreach v $vs { lappend o [format $::esl::numfmt $v] }
                puts $fh "$fi,$id,[join $o ,]"
                incr hrows
                dict lappend hvm $id [lindex $vs 0]
                dict lappend hep $id [lindex $vs 5]
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
    set cand_vmp {{} {}}
    set cand_epp {{} {}}
    if {$nh > 0 && $::esl::has_prev} {
        set cand_vmp [::esl::cand_frames_prev $hvm $hids $rtol $top_n $::esl::prev_eq $::esl::min_incr]
        set cand_epp [::esl::cand_frames_prev $hep $hids $rtol $top_n $::esl::prev_ep $::esl::min_incr]
        ::esl::progress "candidate frames (raw+prev): max_strain [lindex $cand_vmp 0], plastic_strain [lindex $cand_epp 0]"
    }
    set D [lsort -integer -unique [concat [lindex $cand_vm 0] [lindex $cand_ep 0] [lindex $cand_vmp 0] [lindex $cand_epp 0]]]
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

    # ---- F0 pass (cumulative scenes, request frame0_pass 1): frame 0, all part elements -> frame0.csv
    set f0rows 0
    if {$f0pass eq "1"} {
        set t0 [::esl::ms]
        ::esl::progress "frame0.csv: frame 0 ($ne_ch element chunks)"
        ::esl::set_sim $res $post 0
        # fields of the vm_hv and epsp columns only (row_map positions 0 and 5)
        set m0 [lindex $::esl::row_map 0]
        set m5 [lindex $::esl::row_map 5]
        set f0fields [list [lindex $efields $m0]]
        if {$m5 ne "z" && $m5 != $m0} { lappend f0fields [lindex $efields $m5] }
        set ff0 [::esl::open_csv [file join $out frame0.csv] "elem_id,vm_hv,epsp"]
        set ci 0
        foreach ch $echunks {
            incr ci
            ::esl::progress "frame0.csv elements chunk $ci/$ne_ch"
            set acc [::esl::collect $con $qry [lindex $ch 0] element $f0fields "frame0 chunk $ci"]
            if {$m5 ne "z" && $m5 == $m0} {
                # plastic_strain source: epsp column = vm_hv column
                set acc2 [dict create]
                dict for {id vs} $acc { dict set acc2 $id [list [lindex $vs 0] [lindex $vs 0]] }
                set acc $acc2
                unset acc2
            }
            set nf [expr {($m5 ne "z") ? 2 : 1}]
            lassign [::esl::emit $ff0 "" $acc $nf [expr {2 - $nf}]] n m
            incr f0rows $n
            unset acc
        }
        close $ff0
        lappend ::esl::passes "\"F0\":\{\"rows\":$f0rows,\"seconds\":[::esl::secs $t0]\}"
        ::esl::progress "frame0.csv done: $f0rows elements"
    }
    set cum_extra {}
    if {$::esl::has_prev || $f0pass eq "1"} {
        set rsets [expr {$::esl::has_prev ? "\[\"raw\",\"raw+prev\"\]" : "\[\"raw\"\]"}]
        set cum_extra [list cumulative "\{\"prev_file_sha256\":[expr {$prev_sha eq "" ? "null" : [::esl::jstr $prev_sha]}],\"prev_n\":$prev_n,\"frame0\":[expr {$f0pass eq "1" ? "true" : "false"}],\"frame0_rows\":$f0rows,\"rank_sets\":$rsets,\"min_incr\":[::esl::num $::esl::min_incr]\}" \
            candidate_frames_prev "\{\"max_strain\":[::esl::jints [lindex $cand_vmp 0]],\"plastic_strain\":[::esl::jints [lindex $cand_epp 0]]\}" \
            candidate_elems_prev "\{\"max_strain\":[::esl::jints [lindex $cand_vmp 1]],\"plastic_strain\":[::esl::jints [lindex $cand_epp 1]]\}"]
    }

    ::esl::step CloseStack
    catch {hwi CloseStack}
    ::esl::step write_done
    set ::esl::cur_step "done"
    lappend ::esl::steps_done write_csv
    set ch_json {}
    dict for {k2 v2} $::esl::chunk_how { lappend ch_json "[::esl::jstr $k2]:[::esl::jstr $v2]" }
    if {[::esl::write_done $out 1 [list part_id $pid part_title [::esl::jstr $ptitle] \
        part_spec [::esl::jstr $spec] n_frames $nsim \
        frame0_time [::esl::num $t_f0] model_coords [::esl::jstr "coords_minus_disp_frame0"] \
        frame0_disp_max [::esl::num $d0max] frame0_disp_ok [expr {$d0ok ? "true" : "false"}] \
        elems_ok [expr {$elems_ok ? "true" : "false"}] elems_query [::esl::jstr $conn_q] n_conn $nconn \
        n_elems $nelem n_nodes $nnode n_hot $nh \
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
        backup_dir [::esl::jstr [::esl::fwd $::esl::backup_dir]] {*}$cum_extra {*}$::esl::src_members]] eq ""} {
        error "done.json could not be written"
    }
    set ::esl::written 1
    ::esl::progress "extract done: $nelem elements, $nnode nodes, H $nh, D $D, prev $P"
    ::esl::plog_close
}

set ::esl::part_spec ""
set ::esl::part_id ""
set ::esl::tried {}
set ::esl::forced 0
set ::esl::row_map {0 1 2 3 4 5}
set ::esl::src_members {}
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
                passes "\{[join $::esl::passes ,]\}" strain_tried [::esl::tried_json]] \
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
