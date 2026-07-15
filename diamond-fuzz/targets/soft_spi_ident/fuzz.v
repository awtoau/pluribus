// Strategy-2 (synthesize-and-compare) reference for the REG 0x05 ident.
// A hardcoded 64-bit ident is shifted MSB-first onto `miso`, selected by a
// counter clocked on `sck`.  The point: learn how Diamond/LSE encodes a
// hardcoded readback constant in the recovered netlist, then look for the
// same topology in V07 and read off its real ident bytes.
//
// IDENT is a distinguishable pattern (0x0123456789ABCDEF) so that recovering
// it back out of the LUT INITs validates the approach end-to-end.
module fuzz (
    input  wire sck,
    input  wire cs_n,
    output wire miso
);
    localparam [63:0] IDENT = 64'h0123456789ABCDEF;
    reg [5:0] cnt;
    always @(posedge sck) begin
        if (cs_n) cnt <= 6'd0;
        else      cnt <= cnt + 1'b1;
    end
    // Variable index into a constant → LSE synthesises the boolean function
    // whose truth table IS the ident.  That is the encoding we want to read.
    assign miso = IDENT[6'd63 - cnt];
endmodule
