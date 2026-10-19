# esl_h3d_probe.tcl -- list what an h3d contains, so request.txt names can be checked.
#
#   hw -clientconfig hwpost.dat -b -tcl esl_h3d_probe.tcl -input <h3d> -output <dir> [-config <request.txt>]
#
# Writes <dir>/probe.json:
#   {"ok":true,"h3d":...,"subcases":[{"id","label","n_simulations","simulations_head","simulations_tail",
#     "data_types":[{"name","components":[...],"layers":[...]}]}],
#    "selection":{"part_id","element":[{"string","size"}],"node":[...]},"api":{...},"warnings":[]}
# With -config (part_id), tries the part selection strings used by esl_h3d_extract.tcl and
# a 1-element sample query.
#
# NOT VERIFIED against a real HyperView installation. ASCII-only on purpose.

namespace eval ::esl {
    variable warnings {}
    variable api {}
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
proc ::esl::fwd {p} { return [string map [list "\\" "/"] $p] }
proc ::esl::warn {msg} { variable warnings; lappend warnings $msg }
# record whether an API call worked (for the README / debugging)
proc ::esl::try {name script} {
    variable api
    if {[catch {uplevel 1 $script} res]} {
        lappend api $name [::esl::jstr "error: $res"]
        return -code error $res
    }
    lappend api $name [::esl::jstr "ok"]
    return $res
}

proc ::esl::parse_args {arglist} {
    array set a {input "" config "" output ""}
    set n [llength $arglist]
    for {set i 0} {$i < $n} {incr i} {
        set k [string tolower [lindex $arglist $i]]
        if {$k eq "-input" || $k eq "-config" || $k eq "-output"} {
            if {$i + 1 < $n} { incr i; set a([string range $k 1 end]) [lindex $arglist $i] }
        }
    }
    foreach {k ev} {input ESL_INPUT config ESL_CONFIG output ESL_OUTPUT} {
        if {$a($k) eq "" && [info exists ::env($ev)]} { set a($k) $::env($ev) }
    }
    return [array get a]
}

proc ::esl::read_part_id {path} {
    if {$path eq "" || ![file isfile $path]} { return "" }
    set fh [open $path r]
    set pid ""
    while {[gets $fh line] >= 0} {
        set tab [string first "\t" $line]
        if {$tab < 0} { continue }
        if {[string trim [string range $line 0 [expr {$tab - 1}]]] eq "part_id"} {
            set pid [string trim [string range $line [expr {$tab + 1}] end]]
        }
    }
    close $fh
    return $pid
}

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

proc ::esl::run {arglist} {
    array set a [::esl::parse_args $arglist]
    if {$a(output) eq ""} { error "missing -output <dir>" }
    set out [::esl::fwd $a(output)]
    file mkdir $out
    set ::esl::outdir $out
    if {$a(input) eq ""} { error "missing -input <h3d>" }
    set h3d [::esl::fwd $a(input)]
    set ::esl::h3d $h3d
    if {![file isfile $h3d]} { error "h3d not found: $h3d" }
    set pid [::esl::read_part_id [::esl::fwd $a(config)]]

    hwi OpenStack
    hwi GetSessionHandle esl_sess
    esl_sess GetProjectHandle esl_proj
    esl_proj GetPageHandle esl_page [esl_proj GetActivePage]
    esl_page GetWindowHandle esl_win [esl_page GetActiveWindow]
    if {[catch {esl_win SetClientType "Animation"}]} { esl_win SetClientType animation }
    esl_win GetClientHandle esl_post
    set mid [::esl::try AddModel {esl_post AddModel $h3d}]
    esl_post GetModelHandle esl_model $mid
    esl_model GetResultCtrlHandle esl_res
    set subcases {}
    catch {set subcases [::esl::try GetSubcaseList {esl_res GetSubcaseList}]}
    if {[llength $subcases] == 0} {
        catch {::esl::try SetResult {esl_model SetResult $h3d}}
        catch {set subcases [esl_res GetSubcaseList]}
    }
    catch {esl_res GetContourCtrlHandle esl_con}

    set scrows {}
    foreach sc $subcases {
        set label ""
        catch {set label [esl_res GetSubcaseLabel $sc]}
        catch {esl_res SetCurrentSubcase $sc}
        set sims {}
        catch {set sims [::esl::try GetSimulationList {esl_res GetSimulationList $sc}]}
        lassign [::esl::head_tail $sims 3] shead stail
        set dtrows {}
        set dtypes {}
        catch {set dtypes [::esl::try GetDataTypeList {esl_res GetDataTypeList $sc}]}
        foreach dt $dtypes {
            set comps {}
            catch {set comps [esl_res GetDataComponentList $sc $dt]}
            set layers {}
            if {[catch {set layers [esl_res GetLayerList $sc $dt]}]} {
                catch {
                    esl_con SetDataType $dt
                    set layers [esl_con GetLayerList]
                }
            }
            lappend dtrows "\{\"name\":[::esl::jstr $dt],\"components\":[::esl::jarr $comps],\"layers\":[::esl::jarr $layers]\}"
        }
        lappend scrows "\{\"id\":[::esl::jstr $sc],\"label\":[::esl::jstr $label],\"n_simulations\":[llength $sims],\"simulations_head\":[::esl::jarr $shead],\"simulations_tail\":[::esl::jarr $stail],\"data_types\":\[[join $dtrows ,]\]\}"
    }

    set selrow "null"
    if {[string is integer -strict $pid]} {
        set eid [esl_model AddSelectionSet element]
        esl_model GetSelectionSetHandle esl_eset $eid
        set nid [esl_model AddSelectionSet node]
        esl_model GetSelectionSetHandle esl_nset $nid
        set erows [::esl::sel_tries esl_eset $pid]
        set nrows [::esl::sel_tries esl_nset $pid]
        # sample query (first record) with current contour
        set sample ""
        catch {
            esl_eset Clear
            esl_eset Add "component $pid"
            esl_model GetQueryCtrlHandle esl_qry
            esl_qry SetSelectionSet $eid
            esl_qry SetQuery "element.id contour.value"
            esl_qry GetIteratorHandle esl_it
            esl_it First
            if {[esl_it Valid]} { set sample [esl_it GetDataList] }
            esl_it ReleaseHandle
        }
        set nsample ""
        catch {
            esl_nset Clear
            esl_nset Add "component $pid"
            esl_qry SetSelectionSet $nid
            esl_qry SetQuery "node.id node.coords"
            esl_qry GetIteratorHandle esl_it2
            esl_it2 First
            if {[esl_it2 Valid]} { set nsample [esl_it2 GetDataList] }
            esl_it2 ReleaseHandle
        }
        set selrow "\{\"part_id\":$pid,\"element\":$erows,\"node\":$nrows,\"sample_element_query\":[::esl::jstr $sample],\"sample_node_coords\":[::esl::jstr $nsample]\}"
    }
    catch {hwi CloseStack}

    set apis {}
    foreach {k v} $::esl::api { lappend apis "[::esl::jstr $k]:$v" }
    set fh [open [file join $out probe.json] w]
    fconfigure $fh -translation lf -encoding utf-8
    puts $fh "\{\"ok\":true,\"h3d\":[::esl::jstr $h3d],\"subcases\":\[[join $scrows ,]\],\"selection\":$selrow,\"api\":\{[join $apis ,]\},\"warnings\":[::esl::jarr $::esl::warnings]\}"
    close $fh
}

set ::esl::outdir ""
set ::esl::h3d ""
set ::esl::rc 0
if {[catch {::esl::run $::argv} ::esl::err]} {
    catch {hwi CloseStack}
    if {$::esl::outdir ne ""} {
        catch {
            set fh [open [file join $::esl::outdir probe.json] w]
            puts $fh "\{\"ok\":false,\"h3d\":[::esl::jstr $::esl::h3d],\"error\":[::esl::jstr $::esl::err]\}"
            close $fh
        }
    }
    puts stderr "ESL probe failed: $::esl::err"
    set ::esl::rc 1
}
if {![info exists ::ESL_NO_EXIT]} { exit $::esl::rc }
