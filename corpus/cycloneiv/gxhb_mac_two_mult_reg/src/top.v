module top(input clk, input sa, input sb, input [8:0] da, input [8:0] db, input [8:0] da2, input [8:0] db2, output [35:0] r);
  altmult_add #(
    .number_of_multipliers(2),
    .width_a(9),
    .width_b(9),
    .width_result(18),
    .representation_a("UNSIGNED"),
    .representation_b("UNSIGNED"),
    .input_register_a0("UNREGISTERED"),
    .input_register_b0("UNREGISTERED"),
    .multiplier_register0("CLOCK0"),
    .output_register("UNREGISTERED"),
    .signed_register_a("UNREGISTERED"),
    .signed_register_b("UNREGISTERED"),
    .port_signa("PORT_UNUSED"),
    .port_signb("PORT_UNUSED"),
    .intended_device_family("Cyclone IV GX"),
    .lpm_type("altmult_add")
  ) mac (
    .clock0(clk), .ena0(1'b1), .aclr0(1'b0), .dataa({da2, da}), .datab({db2, db}), .result(r));
endmodule
