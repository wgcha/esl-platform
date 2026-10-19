# Minimal mock of the HyperView hwi / poI* Tcl objects used by esl_h3d_extract.tcl.
# Only for tclsh-based tests in this repo; it mimics the call shapes, not HyperView itself.
# Data comes from ::mock::* variables set by the test (see test_tcl_mock.py).
namespace eval ::mock {
    variable seq 0
    variable sets
    variable st
    array set st {sim 0 dtype "" comp "" layer "" query "" qset 0 client Model}
    # failure injection: list of "<type>_<Method>" (e.g. win_SetClientType, post_AddModel,
    # hwi_GetSessionHandle) that raise the numeric error "2051" like HyperView does
    variable fail_at {}
    variable last_error ""
    variable hwc_calls {}
    variable hwc_loaded 0
    # results attached to the model (AddModel reads the model only; SetResult or
    # "hwc open animation modelandresult" load results), and the SetResult arguments seen
    variable res_loaded 0
    variable setresult_calls {}
    variable no_comp_query 0
    variable names [dict create]
}

proc ::mock::maybe_fail {key} {
    if {$key in $::mock::fail_at} {
        set ::mock::last_error "mock: $key failed (2051)"
        return -code error -errorcode {NONE} 2051
    }
}
proc ::mock::call {type method args} {
    ::mock::maybe_fail ${type}_$method
    return [::mock::${type}_$method {*}$args]
}

proc ::mock::obj {name type} {
    if {![string match ::* $name]} { set name ::$name }
    catch {rename $name {}}
    proc $name {method args} "return \[::mock::call $type \$method {*}\$args\]"
}

proc hwc {args} {
    lappend ::mock::hwc_calls $args
    ::mock::maybe_fail "hwc_[lindex $args 0]"
    if {[lrange $args 0 1] eq {open animation}} {
        set ::mock::hwc_loaded 1
        set ::mock::res_loaded [expr {[lindex $args 2] eq "modelandresult"}]
    }
    return
}
proc hwi {cmd args} {
    ::mock::maybe_fail hwi_$cmd
    switch -- $cmd {
        OpenStack - CloseStack { return }
        GetSessionHandle { ::mock::obj [lindex $args 0] sess }
        default { error "hwi: unknown $cmd" }
    }
}
proc ::mock::sess_GetProjectHandle {h} { ::mock::obj $h proj }
proc ::mock::proj_GetActivePage {} { return 1 }
proc ::mock::proj_GetPageHandle {h id} { ::mock::obj $h page }
proc ::mock::page_GetActiveWindow {} { return 1 }
proc ::mock::page_GetWindowHandle {h id} { ::mock::obj $h win }
proc ::mock::sess_GetError {} { set m $::mock::last_error; set ::mock::last_error ""; return $m }
proc ::mock::win_GetClientType {} { return $::mock::st(client) }
proc ::mock::win_SetClientType {t} {
    if {$t ne "Animation"} { error "bad client $t" }
    set ::mock::st(client) $t
}
proc ::mock::win_GetClientHandle {h} { ::mock::obj $h post }
proc ::mock::post_AddModel {f} { set ::mock::res_loaded 0; return 1 }
proc ::mock::post_GetModelReaderList {} { return {H3DReader} }
proc ::mock::post_GetActiveModel {} { return $::mock::hwc_loaded }
proc ::mock::post_GetModelList {} { return [expr {$::mock::hwc_loaded ? 1 : {}}] }
proc ::mock::post_GetModelHandle {h id} { ::mock::obj $h model }
proc ::mock::post_Draw {} { return }
proc ::mock::model_SetResult {f} {
    lappend ::mock::setresult_calls $f
    if {![file isfile $f]} {
        set ::mock::last_error "ERROR:Cannot open result file.  (poIModel::SetResult)"
        return -code error -errorcode {NONE} 2051
    }
    set ::mock::res_loaded 1
    return
}
# like HyperWorks 2026.1: no result control before results are loaded
proc ::mock::model_GetResultCtrlHandle {h} {
    if {!$::mock::res_loaded} {
        set ::mock::last_error "ERROR:No results loaded.  (poIModel::GetResultCtrlHandle)"
        return -code error -errorcode {NONE} 2051
    }
    ::mock::obj $h res
}
proc ::mock::model_GetQueryCtrlHandle {h} { ::mock::obj $h qry }
proc ::mock::model_AddSelectionSet {type} {
    variable seq; variable sets
    incr seq
    set sets($seq,type) $type
    set sets($seq,ids) {}
    return $seq
}
proc ::mock::model_GetSelectionSetHandle {h id} {
    set h ::$h
    catch {rename $h {}}
    proc $h {method args} "return \[::mock::set_\$method $id {*}\$args\]"
}
proc ::mock::set_Clear {id} { variable sets; set sets($id,ids) {} }
proc ::mock::set_GetSize {id} { variable sets; return [llength $sets($id,ids)] }
proc ::mock::set_GetList {id} { variable sets; return $sets($id,ids) }
# Add accumulates (Clear empties). Supported: "all", "component N", "id|element|node <ids/ranges>"
# (space or comma separated, ranges a-b). ::mock::no_range rejects multi-id/range strings,
# ::mock::no_id_add rejects every id string (fallback tests). ::mock::add_calls counts Add calls.
set ::mock::no_range 0
set ::mock::no_id_add 0
set ::mock::add_calls 0
proc ::mock::set_Add {id s} {
    variable sets
    incr ::mock::add_calls
    set t $sets($id,type)
    if {$s eq "all"} {
        set ids {}
        dict for {pid d} $::mock::parts {
            switch -- $t {
                component - part { lappend ids $pid }
                element { lappend ids {*}[dict get $d elems] }
                node { lappend ids {*}[dict get $d nodes] }
            }
        }
        set sets($id,ids) $ids
        return
    }
    if {[regexp {^component (\d+)$} $s -> pid]} {
        set key [expr {$t eq "element" ? "elems" : "nodes"}]
        set new [dict get $::mock::parts $pid $key]
    } elseif {[regexp {^(id|element|node) (.+)$} $s -> kw rest]} {
        if {$kw ne "id" && $kw ne $t} { error "mock: '$kw' ids in a $t set" }
        if {$::mock::no_id_add} { error "mock: id selection not supported" }
        set toks [split [string map {, " "} $rest] " "]
        set new {}
        foreach tok $toks {
            if {$tok eq ""} { continue }
            if {[regexp {^(\d+)-(\d+)$} $tok -> a b]} {
                if {$::mock::no_range} { error "mock: ranges not supported" }
                for {set i $a} {$i <= $b} {incr i} { lappend new $i }
            } elseif {[string is integer -strict $tok]} {
                lappend new $tok
            } else {
                error "mock: bad id token '$tok'"
            }
        }
        if {$::mock::no_range && [llength $new] > 1} { error "mock: several ids not supported" }
        # only existing entities are added
        set all {}
        dict for {pid d} $::mock::parts { lappend all {*}[dict get $d [expr {$t eq "element" ? "elems" : "nodes"}]] }
        set ok {}
        foreach i $new { if {[lsearch -exact $all $i] >= 0} { lappend ok $i } }
        set new $ok
    } else {
        error "mock: unsupported selection '$s'"
    }
    foreach i $new {
        if {[lsearch -exact $sets($id,ids) $i] < 0} { lappend sets($id,ids) $i }
    }
}
proc ::mock::res_GetSubcaseList {} { return {1} }
proc ::mock::res_SetCurrentSubcase {sc} { return }
proc ::mock::res_GetSimulationList {sc} { return $::mock::sims }
# result types: dtinfo = dict type -> {comps {...} layers {...}} (layers {} = no layer list)
if {![info exists ::mock::dtinfo]} {
    set ::mock::dtinfo [dict create \
        Displacement {comps {X Y Z Mag} layers {}} \
        Max_Strain {comps {XX YY ZZ XY YZ ZX vonMises} layers {Mid}} \
        {Plastic Strain} {comps {{Scalar value}} layers {Mid}}]
}
proc ::mock::res_GetDataTypeList {sc} { return [dict keys $::mock::dtinfo] }
proc ::mock::res_GetContourCtrlHandle {h} { ::mock::obj $h con }
set ::mock::sim_calls {}
proc ::mock::res_SetCurrentSimulation {i} { set ::mock::st(sim) $i; lappend ::mock::sim_calls $i }
proc ::mock::con_SetDataType {t} { set ::mock::st(dtype) $t; set ::mock::st(layer) "" }
proc ::mock::con_SetDataComponent {c} { set ::mock::st(comp) $c }
proc ::mock::con_SetLayer {l} { set ::mock::st(layer) $l }
# result system: only "SetResolvedIn {Elemental System}" style is accepted, unless ::mock::no_system is set
set ::mock::no_system 0
set ::mock::system_calls {}
proc ::mock::con_SetResolvedIn {sys} {
    if {$::mock::no_system} { error "mock: SetResolvedIn not available" }
    if {$sys ni {"Elemental System" "Analysis System" "Global System"}} { error "mock: bad system '$sys'" }
    lappend ::mock::system_calls $sys
    set ::mock::st(system) $sys
}
proc ::mock::con_SetAverageMode {m} { return }
proc ::mock::con_SetEnableState {s} { return }
proc ::mock::qry_SetSelectionSet {id} { set ::mock::st(qset) $id }
proc ::mock::qry_SetQuery {q} { set ::mock::st(query) $q }
proc ::mock::qry_GetIteratorHandle {h} {
    variable sets; variable st
    set recs {}
    foreach id $sets($st(qset),ids) {
        if {$st(query) eq "component.id component.name"} {
            if {$::mock::no_comp_query} { error "mock: unknown query field component.name" }
            lappend recs [list $id [dict get $::mock::names $id]]
        } elseif {$st(query) in {element.id node.id}} {
            lappend recs [list $id]
        } elseif {$st(query) eq "node.id node.coords"} {
            lappend recs [list $id [dict get $::mock::coords $id]]
        } else {
            set key [list $st(dtype) $st(comp) $st(layer) $st(sim) $id]
            if {[dict exists $::mock::vals $key]} {
                lappend recs [list $id [dict get $::mock::vals $key]]
            } else {
                lappend recs [list $id N/A]
            }
        }
    }
    set ::mock::it($h) [list 0 $recs]
    catch {rename ::$h {}}
    proc ::$h {method args} "return \[::mock::it_\$method $h {*}\$args\]"
}
proc ::mock::it_First {h} { lset ::mock::it($h) 0 0 }
proc ::mock::it_Next {h} { lset ::mock::it($h) 0 [expr {[lindex $::mock::it($h) 0] + 1}] }
proc ::mock::it_Valid {h} { lassign $::mock::it($h) i r; return [expr {$i < [llength $r]}] }
proc ::mock::it_GetDataList {h} { lassign $::mock::it($h) i r; return [lindex $r $i] }
proc ::mock::it_ReleaseHandle {h} { rename ::$h {} }
proc ::mock::res_GetDataComponentList {sc dt} { return [dict get $::mock::dtinfo $dt comps] }
proc ::mock::res_GetLayerList {sc dt} {
    set l [dict get $::mock::dtinfo $dt layers]
    if {[llength $l] == 0} { error "no layers" }
    return $l
}
proc ::mock::model_GetComponentHandle {h id} {
    catch {rename ::$h {}}
    proc ::$h {method args} "return \[::mock::comp_\$method $id {*}\$args\]"
}
proc ::mock::comp_GetLabel {id} { return [dict get $::mock::names $id] }
proc ::mock::comp_ReleaseHandle {id} { return }
