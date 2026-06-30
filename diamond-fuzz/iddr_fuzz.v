// IDDRXE input DDR capture fuzz target — MachXO2
// Purpose: get Diamond to route IDDRXE on a real input pad so we can read
// back the bitstream and extract the IOLOGIC wire mappings for prjcombine.

module iddr_fuzz (
    input  wire clk,       // clock input — assign to a real pad
    input  wire d0,        // DDR input 0
    input  wire d1,        // DDR input 1
    output reg  qa0,       // Q captured on rising edge
    output reg  qa1,       // Q captured on falling edge
    output reg  qb0,
    output reg  qb1
);

    wire qa0_w, qa1_w, qb0_w, qb1_w;
    wire rst = 1'b0;

    IDDRXE u_iddr0 (
        .D    (d0),
        .SCLK (clk),
        .RST  (rst),
        .Q0   (qa0_w),
        .Q1   (qa1_w)
    );

    IDDRXE u_iddr1 (
        .D    (d1),
        .SCLK (clk),
        .RST  (rst),
        .Q0   (qb0_w),
        .Q1   (qb1_w)
    );

    always @(posedge clk) begin
        qa0 <= qa0_w;
        qa1 <= qa1_w;
        qb0 <= qb0_w;
        qb1 <= qb1_w;
    end

endmodule
