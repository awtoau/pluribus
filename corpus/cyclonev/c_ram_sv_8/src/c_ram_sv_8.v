module c_ram_sv_8 (input logic clk, we, input logic [5:0] waddr, raddr, input logic [7:0] din, output logic [7:0] dout);
  logic [7:0] mem [0:63];
  always_ff @(posedge clk) begin
    if (we) mem[waddr] <= din;
    dout <= mem[raddr];
  end
endmodule
