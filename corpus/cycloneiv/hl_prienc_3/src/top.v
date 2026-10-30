module top (
  input clk,
  output y
);
reg [31:0] stim0;
reg [1:0] pe1;
reg pv2;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  pv2 <= |{stim0[25], stim0[2], stim0[30], stim0[12]};
  casez ({stim0[25], stim0[2], stim0[30], stim0[12]})
    4'b???1: pe1 <= 2'd0;
    4'b??10: pe1 <= 2'd1;
    4'b?100: pe1 <= 2'd2;
    4'b1000: pe1 <= 2'd3;
    default: pe1 <= 2'd0;
  endcase
end
always @(posedge clk) y_q <= (^pe1) ^ pv2;
assign y = y_q;
endmodule
