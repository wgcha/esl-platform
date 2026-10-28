# esl_bead_post.tcl -- HyperView batch: OptiStruct bead (DTPG) Shape Change -> CSV (contract: esl_opt_run.md 9)
#
#   hw -clientconfig hwpost.dat -b -tcl esl_bead_post.tcl -input <deck>_des.h3d -output <dir> [-config <request.txt>]
#
# Reads the design-history h3d written by OptiStruct (<deck>_des.h3d), takes the result type "Shape Change"
# (vector X Y Z, node based) of the LAST design iteration (last simulation of the subcase that has the type)
# and writes into <dir>:
#   shape.csv   node_id,dx,dy,dz              (all nodes of the model; Python checks the set = target nodes)
#   done.json   {"ok":true,"subcase":..,"simulation":..,"n_simulations":..,"n_nodes":..,"shape_type":..}
#               or {"ok":false,"code":"BEAD_POST_FAILED","error":..,"failed_step":..}  (ALWAYS written)
#   progress.log
# Existing outputs are moved to <dir>/_backup/<timestamp>/ first (never deleted).
#
# request.txt (optional, "key<TAB>value" lines, '#' comments): shape_type (Shape Change),
#   shape_comps (X Y Z), subcase (empty = first subcase that has shape_type), simulation (empty = last),
#   node_selection (all).
#
# NOT VERIFIED against a real HyperView installation (written from the hwi/poI* Tcl API docs, same calls as
# esl_h3d_extract.tcl). V-OR-R1 checks it on a real _des.h3d. ASCII-only on purpose.

namespace eval ::eslb {
    variable cur_step start
    variable outdir ""
    variable warnings {}
    variable written 0
    variable plog ""
    variable sfx "[pid]_[expr {[clock clicks] & 0xffffff}]"
}

proc ::eslb::jstr {s} {
    set s [string map [list "\\" "\\\\" "\"" "\\\"" "\n" "\\n" "\r" "\\r" "\t" "\\t"] $s]
    set out ""
    foreach ch [split $s ""] {
        scan $ch %c c
        if {$c < 32} { append out [format "\\u%04x" $c] } else { append out $ch }
    }
    return "\"$out\""
}
proc ::eslb::step {name} {
    set ::eslb::cur_step $name
    ::eslb::log "step $name"
}
proc ::eslb::log {msg} {
    if {$::eslb::plog ne ""} {
        catch {puts $::eslb::plog "[clock format [clock seconds] -format %Y-%m-%dT%H:%M:%S] $msg"; flush $::eslb::plog}
    }
    puts "ESL bead_post: $msg"
}
proc ::eslb::fail {msg} { return -code error -errorcode [list ESL BEAD_POST_FAILED] $msg }

proc ::eslb::parse_args {arglist} {
    set d [dict create -input "" -output "" -config ""]
    foreach {k v} $arglist {
        if {[dict exists $d $k]} { dict set d $k $v }
    }
    return $d
}

proc ::eslb::read_request {path} {
    set cfg [dict create shape_type "Shape Change" shape_comps {X Y Z} subcase "" simulation "" node_selection "all"]
    if {$path eq "" || ![file exists $path]} { return $cfg }
    set fh [open $path r]
    fconfigure $fh -encoding utf-8
    foreach line [split [read $fh] "\n"] {
        set line [string trimright $line "\r"]
        if {[string trim $line] eq "" || [string index [string trim $line] 0] eq "#"} { continue }
        set i [string first "\t" $line]
        if {$i < 0} { continue }
        set k [string trim [string range $line 0 [expr {$i - 1}]]]
        set v [string trim [string range $line [expr {$i + 1}] end]]
        if {[dict exists $cfg $k]} { dict set cfg $k $v }
    }
    close $fh
    return $cfg
}

proc ::eslb::backup_outputs {out} {
    set ts [clock format [clock seconds] -format %Y%m%dT%H%M%S -gmt 1]
    foreach n {shape.csv done.json progress.log} {
        set p [file join $out $n]
        if {[file exists $p]} {
            set dst [file join $out _backup $ts]
            file mkdir $dst
            file rename -force $p [file join $dst $n]
        }
    }
}

proc ::eslb::write_done {ok members} {
    set out $::eslb::outdir
    set body [list "\"ok\":[expr {$ok ? "true" : "false"}]"]
    foreach {k v} $members { lappend body "[::eslb::jstr $k]:$v" }
    set w {}
    foreach x $::eslb::warnings { lappend w [::eslb::jstr $x] }
    lappend body "\"warnings\":\[[join $w ,]\]"
    set txt "\{[join $body ,]\}"
    if {$out eq "" || [catch {
        set fh [open [file join $out done.json] w]
        fconfigure $fh -encoding utf-8 -translation lf
        puts $fh $txt
        close $fh
    } e]} {
        puts stderr "ESL bead_post: done.json not written ($out): $txt"
        return 0
    }
    set ::eslb::written 1
    return 1
}

proc ::eslb::open_model {h3d} {
    set x $::eslb::sfx
    set S eslb_sess_$x
    set P eslb_proj_$x
    set C eslb_post_$x
    set M eslb_model_$x
    set R eslb_res_$x
    set Q eslb_qry_$x
    ::eslb::step OpenStack
    catch {hwi OpenStack}
    ::eslb::step GetSessionHandle
    hwi GetSessionHandle $S
    $S GetProjectHandle $P
    set PG eslb_page_$x
    $P GetPageHandle $PG [$P GetActivePage]
    set W eslb_win_$x
    $PG GetWindowHandle $W [$PG GetActiveWindow]
    set ct ""
    catch {set ct [$W GetClientType]}
    if {[string tolower $ct] ne "animation"} { $W SetClientType Animation }
    $W GetClientHandle $C
    ::eslb::step AddModel
    set mid [$C AddModel $h3d]
    if {![string is integer -strict $mid] || $mid <= 0} { ::eslb::fail "AddModel returned '$mid' for $h3d" }
    $C GetModelHandle $M $mid
    ::eslb::step SetResult
    if {[catch {$M SetResult $h3d} e]} { lappend ::eslb::warnings "SetResult failed: $e" }
    catch {$C Draw}
    ::eslb::step GetResultCtrlHandle
    $M GetResultCtrlHandle $R
    $M GetQueryCtrlHandle $Q
    return [dict create S $S C $C M $M R $R Q $Q]
}

proc ::eslb::run {arglist} {
    set a [::eslb::parse_args $arglist]
    set h3d [dict get $a -input]
    set out [dict get $a -output]
    set ::eslb::outdir $out
    if {$out eq ""} { ::eslb::fail "-output is required" }
    file mkdir $out
    ::eslb::backup_outputs $out
    catch {set ::eslb::plog [open [file join $out progress.log] a]}
    ::eslb::step read_request
    set cfg [::eslb::read_request [dict get $a -config]]
    if {$h3d eq "" || ![file exists $h3d]} { ::eslb::fail "design h3d not found: '$h3d'" }
    set h [::eslb::open_model $h3d]
    set R [dict get $h R]
    set M [dict get $h M]
    set Q [dict get $h Q]
    set C [dict get $h C]
    set stype [dict get $cfg shape_type]
    ::eslb::step GetSubcaseList
    set subcases [$R GetSubcaseList]
    set sc [dict get $cfg subcase]
    if {$sc eq ""} {
        foreach s $subcases {
            if {![catch {$R GetDataTypeList $s} dts] && [lsearch -exact $dts $stype] >= 0} { set sc $s; break }
        }
    }
    if {$sc eq "" || [lsearch -exact $subcases $sc] < 0} {
        ::eslb::fail "no subcase with result type '$stype' (subcases: $subcases)"
    }
    $R SetCurrentSubcase $sc
    set sims [$R GetSimulationList $sc]
    set nsim [llength $sims]
    if {$nsim == 0} { ::eslb::fail "subcase $sc has no simulations (design iterations)" }
    set si [dict get $cfg simulation]
    if {$si eq ""} { set si [expr {$nsim - 1}] }
    ::eslb::step "SetCurrentSimulation $si"
    $R SetCurrentSimulation $si
    catch {$C Draw}
    set dts [$R GetDataTypeList $sc]
    if {[lsearch -exact $dts $stype] < 0} { ::eslb::fail "result type '$stype' not in subcase $sc (available: $dts)" }
    set con eslb_con_$::eslb::sfx
    $R GetContourCtrlHandle $con
    set nset eslb_nset_$::eslb::sfx
    set nsid [$M AddSelectionSet node]
    $M GetSelectionSetHandle $nset $nsid
    $nset Add [dict get $cfg node_selection]
    set vals [dict create]
    set k 0
    foreach comp [dict get $cfg shape_comps] {
        ::eslb::step "contour $stype/$comp"
        $con SetDataType $stype
        $con SetDataComponent $comp
        catch {$con SetAverageMode none}
        catch {$con SetEnableState true}
        catch {$C Draw}
        $Q SetSelectionSet $nsid
        $Q SetQuery "node.id contour.value"
        set it eslb_it_${k}_$::eslb::sfx
        $Q GetIteratorHandle $it
        for {$it First} {[$it Valid]} {$it Next} {
            set rec [concat {*}[$it GetDataList]]
            set id [lindex $rec 0]
            set v [lindex $rec 1]
            if {![string is integer -strict $id] || ![string is double -strict $v]} { continue }
            dict lappend vals $id $v
        }
        catch {$it ReleaseHandle}
        incr k
    }
    ::eslb::step write_csv
    set fh [open [file join $out shape.csv] w]
    fconfigure $fh -translation lf
    puts $fh "node_id,dx,dy,dz"
    set n 0
    set bad 0
    foreach id [lsort -integer [dict keys $vals]] {
        set v [dict get $vals $id]
        if {[llength $v] != 3} { incr bad; continue }
        puts $fh "$id,[format %.17g [lindex $v 0]],[format %.17g [lindex $v 1]],[format %.17g [lindex $v 2]]"
        incr n
    }
    close $fh
    if {$bad} { lappend ::eslb::warnings "$bad nodes without all 3 components skipped" }
    if {$n == 0} { ::eslb::fail "no Shape Change values read" }
    catch {hwi CloseStack}
    ::eslb::step done
    ::eslb::write_done 1 [list subcase [::eslb::jstr $sc] simulation $si n_simulations $nsim n_nodes $n \
        shape_type [::eslb::jstr $stype]]
}

set ::eslb::rc 0
if {[catch {::eslb::run $::argv} ::eslb::err ::eslb::opts]} {
    set ::eslb::code BEAD_POST_FAILED
    catch {hwi CloseStack}
    if {!$::eslb::written} {
        ::eslb::write_done 0 [list code [::eslb::jstr $::eslb::code] error [::eslb::jstr $::eslb::err] \
            failed_step [::eslb::jstr $::eslb::cur_step]]
    }
    ::eslb::log "FAILED at step '$::eslb::cur_step': $::eslb::err"
    set ::eslb::rc 1
}
catch {close $::eslb::plog}
if {![info exists ::ESL_NO_EXIT]} { exit $::eslb::rc }
