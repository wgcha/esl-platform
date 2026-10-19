# esl_h3d_extract.tcl -- HyperView batch extractor for the ESL core (contract: esl_core.md 3.2)
#
#   hw -clientconfig hwpost.dat -b -tcl esl_h3d_extract.tcl -input <h3d> -config <request.txt> -output <dir>
#
# Writes into <dir>:
#   frames.csv  frame_index,time
#   model.csv   node_id,x0,y0,z0                         (target part nodes, first written frame)
#   strain.csv  frame_index,elem_id,layer,exx,eyy,exy    (layer = bottom|top[|mid], tensor shear)
#   disp.csv    frame_index,node_id,ux,uy,uz
#   done.json   {"ok":true,...}  or  {"ok":false,"code":...,"error":...}
#
# request.txt: one "key<TAB>value" per line, '#' lines ignored. Keys:
#   part_id (required), subcase (1), frame_stride (1), strain_type (Strain),
#   strain_comps (XX YY XY), layer_bottom (Lower), layer_top (Upper), layer_mid (empty = skip),
#   shear_is_engineering (0|1), disp_type (Displacement), disp_comps (X Y Z),
#   elem_selection / node_selection (optional HyperView selection string, e.g. "component 12").
#
# NOT VERIFIED against a real HyperView installation (written from the hwi/poI* Tcl API docs).
# Run esl_h3d_probe.tcl first. This file is kept ASCII-only on purpose (Tcl source encoding).

namespace eval ::esl {
    variable warnings {}
    variable h3d ""
}

proc ::esl::fail {code msg} {
    return -code error -errorcode [list ESL $code] $msg
}

proc ::esl::warn {msg} {
    variable warnings
    lappend warnings $msg
}

proc ::esl::jstr {s} {
    set s [string map [list "\\" "\\\\" "\"" "\\\"" "\n" "\\n" "\r" "\\r" "\t" "\\t"] $s]
    return "\"$s\""
}

proc ::esl::jarr {items} {
    set out {}
    foreach it $items { lappend out [::esl::jstr $it] }
    return "\[[join $out ,]\]"
}

proc ::esl::fwd {p} {
    return [string map [list "\\" "/"] $p]
}

proc ::esl::parse_args {arglist} {
    array set a {input "" config "" output ""}
    set n [llength $arglist]
    for {set i 0} {$i < $n} {incr i} {
        set k [string tolower [lindex $arglist $i]]
        if {$k eq "-input" || $k eq "-config" || $k eq "-output"} {
            if {$i + 1 < $n} {
                incr i
                set a([string range $k 1 end]) [lindex $arglist $i]
            }
        }
    }
    foreach {k ev} {input ESL_INPUT config ESL_CONFIG output ESL_OUTPUT} {
        if {$a($k) eq "" && [info exists ::env($ev)]} { set a($k) $::env($ev) }
    }
    return [array get a]
}

proc ::esl::read_config {path} {
    set cfg [dict create part_id "" subcase 1 frame_stride 1 strain_type "Strain" \
        strain_comps "XX YY XY" layer_bottom "Lower" layer_top "Upper" layer_mid "" \
        shear_is_engineering 0 disp_type "Displacement" disp_comps "X Y Z" \
        elem_selection "" node_selection ""]
    if {![file isfile $path]} { ::esl::fail INPUT_INVALID "request file not found: $path" }
    set fh [open $path r]
    fconfigure $fh -encoding utf-8
    while {[gets $fh line] >= 0} {
        set line [string trimright $line "\r\n"]
        set t [string trim $line]
        if {$t eq "" || [string index $t 0] eq "#"} { continue }
        set tab [string first "\t" $line]
        if {$tab < 0} {
            close $fh
            ::esl::fail INPUT_INVALID "request.txt line without TAB: $line"
        }
        set key [string trim [string range $line 0 [expr {$tab - 1}]]]
        set val [string trim [string range $line [expr {$tab + 1}] end]]
        dict set cfg $key $val
    }
    close $fh
    if {![string is integer -strict [dict get $cfg part_id]]} {
        ::esl::fail INPUT_INVALID "part_id missing or not an integer"
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

proc ::esl::set_contour {con dtype comp layer} {
    $con SetDataType $dtype
    $con SetDataComponent $comp
    if {$layer ne ""} { $con SetLayer $layer }
    catch {$con SetAverageMode none}
    catch {$con SetEnableState true}
}

# Run a query; returns flat records {id v1 v2 ...} (nested lists flattened).
proc ::esl::query {qry setid fields} {
    $qry SetSelectionSet $setid
    $qry SetQuery $fields
    $qry GetIteratorHandle esl_it
    set out {}
    if {[catch {
        for {esl_it First} {[esl_it Valid]} {esl_it Next} {
            set rec {}
            foreach v [esl_it GetDataList] { foreach w $v { lappend rec $w } }
            lappend out $rec
        }
    } err]} {
        catch {esl_it ReleaseHandle}
        error $err
    }
    esl_it ReleaseHandle
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

proc ::esl::write_done {out ok extra} {
    variable warnings
    variable h3d
    set fh [open [file join $out done.json] w]
    fconfigure $fh -translation lf -encoding utf-8
    set body "\"ok\":[expr {$ok ? "true" : "false"}],\"h3d\":[::esl::jstr $h3d]"
    foreach {k v} $extra { append body ",[::esl::jstr $k]:$v" }
    append body ",\"warnings\":[::esl::jarr $warnings]"
    puts $fh "\{$body\}"
    close $fh
}

proc ::esl::run {arglist} {
    variable h3d
    array set a [::esl::parse_args $arglist]
    if {$a(output) eq ""} { ::esl::fail INPUT_INVALID "missing -output <dir>" }
    set out [::esl::fwd $a(output)]
    file mkdir $out
    catch {file delete -force [file join $out done.json]}
    set ::esl::outdir $out
    if {$a(input) eq ""} { ::esl::fail INPUT_INVALID "missing -input <h3d>" }
    if {$a(config) eq ""} { ::esl::fail INPUT_INVALID "missing -config <request.txt>" }
    set h3d [::esl::fwd $a(input)]
    if {![file isfile $h3d]} { ::esl::fail TOOL_OUTPUT_MISSING "h3d not found: $h3d" }
    set cfg [::esl::read_config [::esl::fwd $a(config)]]
    set pid [dict get $cfg part_id]
    set sc [dict get $cfg subcase]
    set stride [dict get $cfg frame_stride]
    set stype [dict get $cfg strain_type]
    set dtype [dict get $cfg disp_type]
    set eng [expr {[dict get $cfg shear_is_engineering] eq "1"}]
    set layers [list bottom [dict get $cfg layer_bottom] top [dict get $cfg layer_top]]
    if {[dict get $cfg layer_mid] ne ""} { lappend layers mid [dict get $cfg layer_mid] }

    # ---- session / model
    hwi OpenStack
    hwi GetSessionHandle esl_sess
    esl_sess GetProjectHandle esl_proj
    esl_proj GetPageHandle esl_page [esl_proj GetActivePage]
    esl_page GetWindowHandle esl_win [esl_page GetActiveWindow]
    if {[catch {esl_win SetClientType "Animation"}]} { esl_win SetClientType animation }
    esl_win GetClientHandle esl_post
    set mid [esl_post AddModel $h3d]
    esl_post GetModelHandle esl_model $mid
    esl_model GetResultCtrlHandle esl_res
    set subcases {}
    catch {set subcases [esl_res GetSubcaseList]}
    if {[llength $subcases] == 0} {
        catch {esl_model SetResult $h3d}
        catch {set subcases [esl_res GetSubcaseList]}
    }
    if {[lsearch -exact $subcases $sc] < 0} {
        ::esl::fail H3D_MISSING_RESULT "subcase $sc not in h3d (available: $subcases)"
    }
    esl_res SetCurrentSubcase $sc
    set sims [esl_res GetSimulationList $sc]
    set nsim [llength $sims]
    if {$nsim == 0} { ::esl::fail H3D_MISSING_RESULT "subcase $sc has no simulations" }
    set dtypes [esl_res GetDataTypeList $sc]
    foreach t [list $stype $dtype] {
        if {[lsearch -exact $dtypes $t] < 0} {
            ::esl::fail H3D_MISSING_RESULT "result type '$t' not in subcase $sc (available: $dtypes)"
        }
    }
    esl_res GetContourCtrlHandle esl_con

    # ---- selections
    set eset_id [esl_model AddSelectionSet element]
    esl_model GetSelectionSetHandle esl_eset $eset_id
    set esel [::esl::select_part esl_eset $pid [dict get $cfg elem_selection]]
    set nset_id [esl_model AddSelectionSet node]
    esl_model GetSelectionSetHandle esl_nset $nset_id
    set nsel [::esl::select_part esl_nset $pid [dict get $cfg node_selection]]
    esl_model GetQueryCtrlHandle esl_qry

    set ffr [::esl::open_csv [file join $out frames.csv] "frame_index,time"]
    set fst [::esl::open_csv [file join $out strain.csv] "frame_index,elem_id,layer,exx,eyy,exy"]
    set fds [::esl::open_csv [file join $out disp.csv] "frame_index,node_id,ux,uy,uz"]
    set nframes 0
    set nelem 0
    set nnode 0
    set scomps [dict get $cfg strain_comps]
    set dcomps [dict get $cfg disp_comps]
    for {set fi 0} {$fi < $nsim} {incr fi $stride} {
        esl_res SetCurrentSimulation $fi
        catch {esl_post Draw}
        set t [::esl::label_time [lindex $sims $fi]]
        if {$t eq ""} {
            set t $fi
            ::esl::warn "frame $fi: no time in label '[lindex $sims $fi]'; time = frame index"
        }
        puts $ffr "$fi,$t"

        if {$nframes == 0} {
            # initial coordinates (first written frame; frame 0 is expected to be undeformed)
            set fmo [::esl::open_csv [file join $out model.csv] "node_id,x0,y0,z0"]
            foreach rec [::esl::query esl_qry $nset_id "node.id node.coords"] {
                if {[llength $rec] >= 4} {
                    puts $fmo "[lindex $rec 0],[lindex $rec 1],[lindex $rec 2],[lindex $rec 3]"
                }
            }
            close $fmo
            if {$fi != 0} { ::esl::warn "model.csv written at frame $fi (not 0)" }
        }

        # strain tensor per layer
        foreach {lname hvlayer} $layers {
            set vals {}
            foreach c $scomps {
                ::esl::set_contour esl_con $stype $c $hvlayer
                lappend vals [::esl::contour_values esl_qry $eset_id element "strain $c $hvlayer frame $fi"]
            }
            lassign $vals dxx dyy dxy
            set cnt 0
            dict for {eid exx} $dxx {
                if {![dict exists $dyy $eid] || ![dict exists $dxy $eid]} { continue }
                set exy [dict get $dxy $eid]
                if {$eng} { set exy [expr {0.5 * $exy}] }
                puts $fst "$fi,$eid,$lname,$exx,[dict get $dyy $eid],$exy"
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
            ::esl::set_contour esl_con $dtype $c ""
            lappend vals [::esl::contour_values esl_qry $nset_id node "disp $c frame $fi"]
        }
        lassign $vals dx dy dz
        set cnt 0
        dict for {nid ux} $dx {
            if {![dict exists $dy $nid] || ![dict exists $dz $nid]} { continue }
            puts $fds "$fi,$nid,$ux,[dict get $dy $nid],[dict get $dz $nid]"
            incr cnt
        }
        if {$cnt == 0} { ::esl::fail H3D_MISSING_RESULT "no displacement values at frame $fi" }
        if {$cnt > $nnode} { set nnode $cnt }
        incr nframes
    }
    close $ffr
    close $fst
    close $fds
    catch {hwi CloseStack}
    ::esl::write_done $out 1 [list n_frames $nframes n_elems $nelem n_nodes $nnode \
        subcase [::esl::jstr $sc] elem_selection [::esl::jstr [lindex $esel 0]] \
        node_selection [::esl::jstr [lindex $nsel 0]]]
}

set ::esl::outdir ""
set ::esl::rc 0
if {[catch {::esl::run $::argv} ::esl::err ::esl::opts]} {
    set ::esl::code TOOL_LOG_ERROR
    set ::esl::ec [dict get $::esl::opts -errorcode]
    if {[lindex $::esl::ec 0] eq "ESL"} { set ::esl::code [lindex $::esl::ec 1] }
    catch {hwi CloseStack}
    if {$::esl::outdir ne ""} {
        catch {::esl::write_done $::esl::outdir 0 [list code [::esl::jstr $::esl::code] \
            error [::esl::jstr $::esl::err]]}
    }
    puts stderr "ESL extract failed: $::esl::code: $::esl::err"
    set ::esl::rc 1
}
if {![info exists ::ESL_NO_EXIT]} { exit $::esl::rc }
