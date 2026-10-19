# esl_h3d_probe.tcl -- list what an h3d contains (components = Radioss parts, subcases, result
# types, components, layers), so the part and result names for esl_h3d_extract.tcl can be checked.
#
#   hw -clientconfig hwpost.dat -b -tcl esl_h3d_probe.tcl -input <h3d> -output <dir> [-part <title|id>] [-config <request.txt>]
#
# Writes <dir>/probe.json (ALWAYS, also on error; if <dir> cannot be written: stderr + a copy
# esl_probe_fallback.json next to this script):
#   ok:true  {"ok","h3d","part_spec","part_id","components":[{"id","name","n_elems"}],
#             "subcases":[{"id","label","n_simulations","simulations_head","simulations_tail",
#               "data_types":[{"name","components","layers"}]}],
#             "selection":{...}|null,"steps_done","api","traces","env","warnings"}
#   ok:false {"ok":false,"h3d","failed_step","error","errorCode","errorInfo","steps_done","api",
#             "traces","env","components","subcases","warnings"}
# -part (or part_id / part_title in request.txt): also tries the part selection strings used by
# esl_h3d_extract.tcl and a 1-element sample query. Title match ignores case, blanks, underscores.
#
# NOT VERIFIED against a real HyperView installation. ASCII-only on purpose.

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
    ::esl::do GetResultCtrlHandle {$M GetResultCtrlHandle $R}
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

proc ::esl::head_tail {lst n} {
    set len [llength $lst]
    if {$len <= 2 * $n} { return [list $lst {}] }
    return [list [lrange $lst 0 [expr {$n - 1}]] [lrange $lst end-[expr {$n - 1}] end]]
}

proc ::esl::sel_tries {sethandle pid} {
    set rows {}
    foreach s [list "component $pid" "comp $pid" "part $pid" "all"] {
        catch {$sethandle Clear}
        set n -1
        if {[catch {$sethandle Add $s} err]} {
            lappend rows "\{\"string\":[::esl::jstr $s],\"size\":-1,\"error\":[::esl::jstr $err]\}"
            continue
        }
        catch {set n [$sethandle GetSize]}
        lappend rows "\{\"string\":[::esl::jstr $s],\"size\":$n\}"
    }
    return "\[[join $rows ,]\]"
}

# subcases / simulations / data types / components / layers -> ::esl::subcases_json
proc ::esl::probe_results {M R} {
    variable sfx
    set subcases {}
    catch {set subcases [::esl::do GetSubcaseList {$R GetSubcaseList}]}
    if {[llength $subcases] == 0} {
        catch {::esl::do SetResult {$M SetResult $::esl::h3d}}
        catch {set subcases [::esl::do GetSubcaseList_retry {$R GetSubcaseList}]}
    }
    if {[llength $subcases] == 0} { ::esl::warn "no subcases found" }
    set CON esl_con_$sfx
    catch {::esl::do GetContourCtrlHandle {$R GetContourCtrlHandle $CON}}
    set scrows {}
    foreach sc $subcases {
        ::esl::step "subcase $sc"
        set label ""
        catch {set label [$R GetSubcaseLabel $sc]}
        catch {$R SetCurrentSubcase $sc}
        set sims {}
        catch {set sims [::esl::do "GetSimulationList $sc" {$R GetSimulationList $sc}]}
        lassign [::esl::head_tail $sims 3] shead stail
        set dtrows {}
        set dtypes {}
        catch {set dtypes [::esl::do "GetDataTypeList $sc" {$R GetDataTypeList $sc}]}
        foreach dt $dtypes {
            set comps {}
            catch {set comps [$R GetDataComponentList $sc $dt]}
            set layers {}
            if {[catch {set layers [$R GetLayerList $sc $dt]}]} {
                catch {
                    $CON SetDataType $dt
                    set layers [$CON GetLayerList]
                }
            }
            lappend dtrows "\{\"name\":[::esl::jstr $dt],\"components\":[::esl::jarr $comps],\"layers\":[::esl::jarr $layers]\}"
        }
        lappend scrows "\{\"id\":[::esl::jstr $sc],\"label\":[::esl::jstr $label],\"n_simulations\":[llength $sims],\"simulations_head\":[::esl::jarr $shead],\"simulations_tail\":[::esl::jarr $stail],\"data_types\":\[[join $dtrows ,]\]\}"
        set ::esl::subcases_json "\[[join $scrows ,]\]"
    }
    set ::esl::subcases_json "\[[join $scrows ,]\]"
}

proc ::esl::probe_selection {M Q pid} {
    variable sfx
    ::esl::step "selection part $pid"
    set ES esl_eset_$sfx
    set NS esl_nset_$sfx
    set eid [::esl::do AddSelectionSet_element {$M AddSelectionSet element}]
    ::esl::do GetSelectionSetHandle_element {$M GetSelectionSetHandle $ES $eid}
    set nid [::esl::do AddSelectionSet_node {$M AddSelectionSet node}]
    ::esl::do GetSelectionSetHandle_node {$M GetSelectionSetHandle $NS $nid}
    set erows [::esl::sel_tries $ES $pid]
    set nrows [::esl::sel_tries $NS $pid]
    set sample ""
    catch {
        $ES Clear
        $ES Add "component $pid"
        $Q SetSelectionSet $eid
        $Q SetQuery "element.id contour.value"
        $Q GetIteratorHandle esl_it_$sfx
        esl_it_$sfx First
        if {[esl_it_$sfx Valid]} { set sample [esl_it_$sfx GetDataList] }
        esl_it_$sfx ReleaseHandle
    }
    set nsample ""
    catch {
        $NS Clear
        $NS Add "component $pid"
        $Q SetSelectionSet $nid
        $Q SetQuery "node.id node.coords"
        $Q GetIteratorHandle esl_it2_$sfx
        esl_it2_$sfx First
        if {[esl_it2_$sfx Valid]} { set nsample [esl_it2_$sfx GetDataList] }
        esl_it2_$sfx ReleaseHandle
    }
    return "\{\"part_id\":$pid,\"element\":$erows,\"node\":$nrows,\"sample_element_query\":[::esl::jstr $sample],\"sample_node_coords\":[::esl::jstr $nsample]\}"
}

proc ::esl::run {arglist} {
    ::esl::step args
    array set a [::esl::parse_args $arglist]
    set ::esl::outdir [::esl::fwd $a(output)]
    if {$a(input) ne ""} { set ::esl::h3d [::esl::fwd $a(input)] }
    ::esl::collect_env $::esl::h3d
    if {$a(output) eq ""} { error "missing -output <dir>" }
    ::esl::step mkdir_output
    file mkdir $::esl::outdir
    ::esl::step check_input
    if {$a(input) eq ""} { error "missing -input <h3d>" }
    if {![file isfile $::esl::h3d]} { error "h3d not found: $::esl::h3d" }
    ::esl::step read_request
    set cfg [::esl::read_request [::esl::fwd $a(config)] [dict create part_id "" part_title ""]]
    set spec [string trim $a(part)]
    if {$spec eq ""} { set spec [dict get $cfg part_id] }
    if {$spec eq ""} { set spec [dict get $cfg part_title] }
    set ::esl::part_spec $spec

    set h [::esl::open_model $::esl::h3d]
    set M [dict get $h M]
    set R [dict get $h R]
    set Q [dict get $h Q]
    if {[catch {::esl::list_components $M $Q 1} e]} { ::esl::warn "component list failed at $::esl::cur_step: $e" }
    ::esl::probe_results $M $R

    set selrow "null"
    set pid ""
    if {$spec ne ""} {
        ::esl::step resolve_part
        if {[catch {set pid [::esl::resolve_part $spec]} e]} {
            ::esl::warn $e
        } else {
            set ::esl::part_id $pid
            set selrow [::esl::probe_selection $M $Q $pid]
        }
    }
    ::esl::step CloseStack
    catch {hwi CloseStack}
    ::esl::step write_json
    set pidj [expr {[string is integer -strict $pid] ? $pid : "null"}]
    set body "\{\"ok\":true,\"h3d\":[::esl::jstr $::esl::h3d],\"part_spec\":[::esl::jstr $spec],\"part_id\":$pidj,\"subcases\":$::esl::subcases_json,\"selection\":$selrow,[::esl::trace_members],\"warnings\":[::esl::jarr $::esl::warnings]\}"
    if {[::esl::write_json $::esl::outdir probe.json esl_probe_fallback.json $body] eq ""} {
        error "probe.json could not be written"
    }
    set ::esl::written 1
}

set ::esl::subcases_json "\[\]"
set ::esl::part_spec ""
set ::esl::part_id ""
set ::esl::written 0
set ::esl::rc 0
if {[catch {::esl::run $::argv} ::esl::err ::esl::opts]} {
    catch {hwi CloseStack}
    if {!$::esl::written} {
        set ::esl::body "\{\"ok\":false,\"h3d\":[::esl::jstr $::esl::h3d],\"part_spec\":[::esl::jstr $::esl::part_spec],[::esl::diag_members $::esl::err $::esl::opts],[::esl::trace_members],\"subcases\":$::esl::subcases_json,\"warnings\":[::esl::jarr $::esl::warnings]\}"
        ::esl::write_json $::esl::outdir probe.json esl_probe_fallback.json $::esl::body
    }
    puts stderr "ESL probe failed at step '$::esl::cur_step': $::esl::err"
    set ::esl::rc 1
}
if {![info exists ::ESL_NO_EXIT]} { exit $::esl::rc }
