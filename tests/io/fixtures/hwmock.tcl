# Minimal mock of the HyperView hwi / poI* Tcl objects used by esl_h3d_extract.tcl.
# Only for tclsh-based tests in this repo; it mimics the call shapes, not HyperView itself.
# Data comes from ::mock::* variables set by the test (see test_tcl_mock.py).
namespace eval ::mock {
    variable seq 0
    variable sets
    variable st
    array set st {sim 0 dtype "" comp "" layer "" query "" qset 0}
}

proc ::mock::obj {name type} {
    if {![string match ::* $name]} { set name ::$name }
    catch {rename $name {}}
    proc $name {method args} "return \[::mock::${type}_\$method {*}\$args\]"
}

proc hwi {cmd args} {
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
proc ::mock::win_SetClientType {t} { if {$t ne "Animation"} { error "bad client $t" } }
proc ::mock::win_GetClientHandle {h} { ::mock::obj $h post }
proc ::mock::post_AddModel {f} { return 1 }
proc ::mock::post_GetModelHandle {h id} { ::mock::obj $h model }
proc ::mock::post_Draw {} { return }
proc ::mock::model_GetResultCtrlHandle {h} { ::mock::obj $h res }
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
proc ::mock::set_Add {id s} {
    variable sets
    if {![regexp {^component (\d+)$} $s -> pid]} { error "mock: unsupported selection '$s'" }
    set key [expr {$sets($id,type) eq "element" ? "elems" : "nodes"}]
    set sets($id,ids) [dict get $::mock::parts $pid $key]
}
proc ::mock::res_GetSubcaseList {} { return {1} }
proc ::mock::res_SetCurrentSubcase {sc} { return }
proc ::mock::res_GetSimulationList {sc} { return $::mock::sims }
proc ::mock::res_GetDataTypeList {sc} { return {Strain Displacement} }
proc ::mock::res_GetContourCtrlHandle {h} { ::mock::obj $h con }
proc ::mock::res_SetCurrentSimulation {i} { set ::mock::st(sim) $i }
proc ::mock::con_SetDataType {t} { set ::mock::st(dtype) $t; set ::mock::st(layer) "" }
proc ::mock::con_SetDataComponent {c} { set ::mock::st(comp) $c }
proc ::mock::con_SetLayer {l} { set ::mock::st(layer) $l }
proc ::mock::con_SetAverageMode {m} { return }
proc ::mock::con_SetEnableState {s} { return }
proc ::mock::qry_SetSelectionSet {id} { set ::mock::st(qset) $id }
proc ::mock::qry_SetQuery {q} { set ::mock::st(query) $q }
proc ::mock::qry_GetIteratorHandle {h} {
    variable sets; variable st
    set recs {}
    foreach id $sets($st(qset),ids) {
        if {$st(query) eq "node.id node.coords"} {
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
proc ::mock::res_GetDataComponentList {sc dt} {
    return [expr {$dt eq "Strain" ? {XX YY ZZ XY YZ ZX vonMises} : {X Y Z Mag}}]
}
proc ::mock::res_GetLayerList {sc dt} {
    if {$dt ne "Strain"} { error "no layers" }
    return {Lower Upper Max Min}
}
