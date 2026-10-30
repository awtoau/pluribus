module top(input clk, input en, input rst, input sa, input sb, input [17:0] da, input [17:0] db, output [35:0] r);
  altmult_add #(
    .number_of_multipliers(1),
    .width_a(18),
    .width_b(18),
    .width_result(36),
    .representation_a("UNSIGNED"),
    .representation_b("UNSIGNED"),
    .input_register_a0("UNREGISTERED"),
    .input_register_b0("UNREGISTERED"),
    .multiplier_register0("UNREGISTERED"),
    .output_register("CLOCK0"),
    .signed_register_a("UNREGISTERED"),
    .signed_register_b("UNREGISTERED"),
    .port_signa("PORT_UNUSED"),
    .port_signb("PORT_UNUSED"),
    .output_aclr("ACLR0"),
    .intended_device_family("Cyclone IV GX"),
    .lpm_type("altmult_add")
  ) mac (
    .clock0(clk), .ena0(1'b1), .aclr0(rst), .dataa(da), .datab(db), .result(r));
endmodule
